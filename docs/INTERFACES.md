# INTERFACES.md — pinned module contracts for parallel implementation

Every module below is implemented by a different agent in parallel. **Implement exactly
these signatures** — other agents are coding against them right now. Already written (do
not modify): `app/config.py`, `app/db.py`, `app/models.py`, `app/schemas.py`,
`pyproject.toml`, `.env.example`. Read them plus `docs/SPEC.md` before writing code.

Conventions: Python 3.11, full type hints, async where marked. `contract_body` always means
the parsed contract document dict (SPEC §Contract). `path` values `"http" | "agent"`;
mock executions still report `path="agent"` (mock stands in for the agent path).

---

## app/services/validate.py

```python
class InputValidationError(ValueError): ...
class OutputValidationError(ValueError): ...

def validate_input(data: dict, schema: dict) -> dict:
    """jsonschema-validate; returns a copy with top-level property defaults applied
    (e.g. limit default 5). Raises InputValidationError with readable message."""

def validate_output(data: dict, schema: dict) -> None:
    """jsonschema-validate. Raises OutputValidationError."""

def get_path(data: dict, dotted: str) -> object:
    """Resolve 'stories.0.title' style paths; numeric segments index lists.
    Raises KeyError/IndexError if missing."""

def check_health(data: dict, health: dict | None, latency_ms: int, path: str) -> bool:
    """SPEC §Validation. min_array_length {path,min}; required_paths list;
    max_latency_ms — returns False for agent path over budget, only warn-logs for http.
    None/empty health → True."""
```

## app/services/http_executors/base.py

```python
ALLOWED_HOSTS: set[str]  # {"hacker-news.firebaseio.com"} — SSRF allowlist

class SSRFBlockedError(Exception): ...
class MapperNotFoundError(Exception): ...

def assert_host_allowed(url: str) -> None:
    """urlparse; raise SSRFBlockedError unless scheme==https and host in ALLOWED_HOSTS."""

def get_client() -> httpx.AsyncClient:
    """Module-level singleton AsyncClient (timeout 10s), created lazily."""

async def get_json(url: str) -> object:
    """assert_host_allowed → GET via singleton → raise_for_status → .json()."""

MapperFn = Callable[[dict, dict], Awaitable[dict]]  # (contract_body, input) -> output data

def register_mapper(name: str) -> Callable[[MapperFn], MapperFn]: ...
def get_mapper(name: str) -> MapperFn:  # raises MapperNotFoundError
    ...

async def execute_http(contract_body: dict, input: dict) -> dict:
    """Look up contract_body['http']['mapper'] and invoke it. Raises if http disabled
    or mapper missing."""
```

## app/services/http_executors/hn_firebase.py

```python
@register_mapper("hn_firebase_v0")
async def run(contract_body: dict, input: dict) -> dict:
    """SPEC §HN Firebase executor. limit = int(input.get('limit', 5)).
    topstories → first `limit` ids (each coerced via int(); non-int → error) →
    parallel item fetch with asyncio.Semaphore(10) + gather → mapper dict per SPEC.
    Returns {"stories": [...]}."""
```

`app/services/http_executors/__init__.py` must `from app.services.http_executors import
hn_firebase  # noqa` so the mapper self-registers on package import.

## app/services/h_client.py

```python
@dataclass
class HResult:
    answer: dict
    session_id: str | None
    cost_usd: float | None
    engine: str  # "h" | "mock"

def render_prompt(template: str, variables: dict) -> str:
    """Safe {{var}} substitution only (regex replace). Unknown vars left as-is. No eval."""

async def run_h_session(prompt: str, output_schema: dict) -> HResult:
    """Mock mode (settings.h_mode == 'mock'): await asyncio.sleep(1.5); return
    deterministic fake stories honoring a 'limit' hint parsed from the prompt if present
    (default 5): rank i, title f"Mock HN story #{i}", url/hn_url https://news.ycombinator.com/item?id=<40000000+i>,
    points 100-i. engine='mock', cost_usd 0.0, session_id None.
    Live mode: lazy-import hai_agents inside the function (package optional — ImportError
    → RuntimeError with install hint); build client, run client.run_session(agent=settings.hai_agent,
    messages=prompt, answer_schema=<dynamic pydantic model or raw schema per SDK>) in
    asyncio.to_thread; map answer/session/cost. Never log the API key."""

async def execute_agent(contract_body: dict, input: dict) -> HResult:
    """render_prompt(contract_body['agent']['prompt_template'],
    {**input, 'site': contract_body['site'], 'goal': contract_body['goal']}) →
    run_h_session(prompt, contract_body['output_schema'])."""
```

## app/services/contract_store.py

```python
def get_or_create_default_workspace(db: Session) -> models.Workspace:
    """name='default'; single row."""

def get_workflow(db: Session, id_or_slug: str) -> models.Workflow | None: ...

def next_version(db: Session, workflow_id: str) -> int:  # max(version)+1, start 1
    ...

def insert_contract(db: Session, workflow: models.Workflow, body: dict, method: str,
                    status: str = "draft") -> models.Contract:
    """body gains id/workflow_id/version before storing (body_json = json.dumps(body))."""

def activate_contract(db: Session, workflow: models.Workflow,
                      contract: models.Contract) -> None:
    """Previous active → 'deprecated'; contract.status='active';
    workflow.active_contract_id=contract.id; workflow.updated_at=now_iso();
    export body to contracts/<slug>-v<version>.json (best effort, ignore IO errors)."""

def get_active_contract(db: Session, workflow: models.Workflow) -> models.Contract | None: ...
def get_contract_by_version(db: Session, workflow_id: str, version: int) -> models.Contract | None: ...
def contract_out(c: models.Contract) -> schemas.ContractOut: ...
```

## app/services/compiler.py

```python
HN_HOSTS = {"news.ycombinator.com"}

def is_hn(workflow: models.Workflow) -> bool:
    """urlparse(site).hostname in HN_HOSTS or slug.startswith('hn')."""

def build_contract_body(workflow: models.Workflow, *, hn: bool, engine: str,
                        session_id: str | None, notes: str) -> dict:
    """SPEC §Contract shape. hn=True → http block with hn_firebase_v0 steps + mapper,
    method='hybrid', agent block enabled as fallback. hn=False → no http block
    (http={'enabled': False}), method='agent'. agent.prompt_template per SPEC rules
    (include {{site}}, field list from output_schema, 'return only data matching schema;
    do not invent URLs')."""

async def compile_workflow(db: Session, workflow: models.Workflow,
                           req: schemas.CompileRequest) -> schemas.CompileResponse:
    """CompileJob(status='running', engine=resolved) → resolved engine: req.engine
    'auto' → 'h' if get_settings().h_mode=='live' else 'mock'; 'h' forced without live →
    fall back to 'mock' with note. For engine 'h': call
    h_client.run_h_session(compile probe prompt, workflow output schema) to verify the
    goal once and capture session_id (failure → job 'failed', error recorded, no
    contract, return response with contract=None). Mock engine: skip the probe.
    Then build_contract_body, insert_contract, activate if req.activate,
    job status='completed', result_contract_id set, finished_at=now_iso().
    Returns CompileResponse(job=..., contract=...)."""
```

## app/services/router.py  (runtime router — SPEC §Runtime router algorithm)

```python
class PathUnavailableError(ValueError):
    """force_path names a path the contract doesn't have configured/enabled."""

class RunFailedError(Exception):
    def __init__(self, run_id: str, contract: models.Contract,
                 errors: list[dict]):  # [{"path": "http", "error": "..."}]
        ...

def resolve_path_order(method: str, force_path: str | None,
                       http_enabled: bool, agent_enabled: bool) -> list[str]:
    """Per SPEC. Raises PathUnavailableError if the resulting order is empty or
    force_path unavailable."""

async def run_workflow(db: Session, workflow: models.Workflow,
                       req: schemas.RunRequest) -> schemas.RunResponse:
    """Load contract (req.contract_version or active; none → LookupError).
    validate_input (InputValidationError propagates). Iterate resolve_path_order:
    time with time.perf_counter; http → execute_http, agent → execute_agent (capture
    HResult.session_id/cost_usd). validate_output then check_health; failure of either →
    record error, next path. First success → persist Run(ok=1, path=...) and return
    RunResponse. All fail → persist Run(ok=0, path=last attempted, error=json of errors)
    and raise RunFailedError. Always one Run row per invocation."""
```

## app/routers/*.py + app/main.py

```python
# health.py:    router = APIRouter();  GET /health → schemas.HealthOut
# runs.py:      router = APIRouter(prefix="/v1/runs");  GET /{run_id} → RunRecordOut (404)
# workflows.py: router = APIRouter(prefix="/v1/workflows")
#   POST ""                          → WorkflowOut (201; get_or_create_default_workspace;
#                                      409 on duplicate slug)
#   GET ""                           → list[WorkflowOut]
#   GET "/{id_or_slug}"              → WorkflowOut (404)
#   GET "/{id_or_slug}/contracts"    → list[ContractOut]
#   GET "/{id_or_slug}/openapi.json" → dict: OpenAPI 3.1 fragment, single path
#                                      /v1/workflows/{slug}/run, requestBody = active
#                                      contract input_schema, 200 response = RunResponse
#                                      envelope with data = output_schema
#   POST "/{id_or_slug}/compile"     → CompileResponse
#   POST "/{id_or_slug}/recompile"   → CompileResponse (same handler; bumps version)
#   POST "/{id_or_slug}/run"         → RunResponse
#   GET "/{id_or_slug}/runs?limit=20"→ list[RunRecordOut] (desc by created_at)
#   GET runs list route MUST be declared before "/{id_or_slug}" catch-alls as needed.
#
# Error mapping (workflows.py): LookupError/None workflow → 404;
# InputValidationError/PathUnavailableError/ValueError → 400 {"detail": ...};
# RunFailedError → JSONResponse 502 {"ok": false, "errors": e.errors, "run_id": e.run_id}.
#
# main.py: FastAPI(title="API H", lifespan=...) — lifespan calls db.init_db() and
# imports app.services.http_executors (mapper registration). include health, workflows,
# runs routers. Mount static: GET "/" serves static/index.html via FileResponse
# (app.mount("/static", StaticFiles(directory="static"), name="static") + explicit "/"
# route). `app = create_app()` module-level for `uvicorn app.main:app`.
```

## tests/ (agent 4)

`tests/conftest.py` MUST set env before any `app.*` import:

```python
import os, tempfile
_tmp = tempfile.mkdtemp()
os.environ["API_H_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["API_H_MOCK_H"] = "true"
os.environ["HAI_API_KEY"] = ""
```

Fixtures: `client` → `fastapi.testclient.TestClient(app)` (import inside fixture, after
env); fresh DB per test via `Base.metadata.drop_all/create_all`; helper to create the
HN workflow + hybrid contract directly through services. Mock-agent sleep: monkeypatch
`asyncio.sleep` inside h_client or accept the 1.5s (keep suite < 30s). Firebase calls
mocked with `respx` — tests never hit the network. Required tests per SPEC §Tests.

## scripts + static + README (agent 5)

- `scripts/seed.py` — runnable as `python scripts/seed.py` from repo root
  (`sys.path.insert(0, ...)` if needed); creates default workspace + `hn-top-stories`
  workflow (schemas exactly per SPEC §Contract) via services directly (no server
  needed), compiles engine=auto activate=true (asyncio.run), prints curl examples.
  Idempotent (existing workflow → recompile).
- `scripts/demo_curl.sh` — per SPEC §Seed + demo, executable.
- `static/index.html` — per SPEC §Static UI. Vanilla JS fetch against same origin.
  meta.path + latency displayed huge.
- `README.md` — per SPEC §README (all sections, tables, ascii diagram, pitch snippets,
  caveats verbatim in spirit).
