# API H — Execution Spec (source of truth)

Local MVP: compile a website workflow once via H Company Computer-Use (or a mock), store a
versioned **contract** in SQLite, serve `POST /run` that prefers cheap HTTP, falls back to
re-triggering the agent, and never pretends every site becomes a free instant API.

Product thesis: **H is the compiler and the fallback; the contract + router is the product;
the local database is the source of truth for versions and runs.**

Analogy for code comments: H agent = person walking the building; contract = receptionist
window; HTTP path = phone the records room; agent path = send the person again.

## MVP done when

- SQLite persists workspaces, workflows, contracts, runs, compile_jobs
- `POST /compile` runs H agent once (or mock) with structured output schema, saves contract v1
- Demo workflow "Hacker News top stories" graduates to `method: http`/`hybrid` using the
  Firebase HN API
- `POST /run` returns JSON + `meta.path ∈ {http, agent, mock}` and latency
- `force_path=agent` re-triggers H (or mock) for contrast demo
- OpenAPI-ish export of the contract run operation
- README with curl demo script and ascii architecture diagram
- Unit tests for HTTP path + schema validation, all offline (no network, no H key)
- `.env.example` for `HAI_API_KEY`

## Non-goals

Browserbase/Autobrowse runtime, Stagehand, billing, HAR→OpenAPI pipeline, HoloTab import,
skill marketplace, full self-healing doctor (manual `POST /recompile` only), desktop
computer-use.

## Stack

Python 3.11+, FastAPI, SQLAlchemy 2.0 + SQLite, Pydantic v2, httpx, jsonschema, pytest,
uvicorn. `hai-agents` optional (live mode only); the app must run and pass tests without it
and without any API key.

## Domain objects

| Entity | Meaning |
|---|---|
| Workspace | Local tenant (single default workspace OK) |
| Workflow | Named job: goal, site origin, input/output JSON Schema |
| Contract | Immutable versioned fulfillment plan for a workflow |
| Run | One invocation of a workflow against a contract |
| CompileJob | Job that produces a contract |

## Contract document (stored as JSON in contracts.body_json)

```json
{
  "id": "uuid",
  "workflow_id": "uuid",
  "version": 1,
  "status": "draft | active | deprecated",
  "title": "Hacker News top stories",
  "site": "https://news.ycombinator.com",
  "goal": "Return top N front-page stories with rank, title, url, points",
  "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "default": 5}}},
  "output_schema": {
    "type": "object",
    "required": ["stories"],
    "properties": {
      "stories": {
        "type": "array",
        "items": {
          "type": "object",
          "required": ["rank", "title", "url", "points"],
          "properties": {
            "rank": {"type": "integer"},
            "title": {"type": "string"},
            "url": {"type": "string"},
            "points": {"type": "integer"},
            "hn_url": {"type": "string"}
          }
        }
      }
    }
  },
  "method": "http | agent | hybrid",
  "http": {
    "enabled": true,
    "description": "HN Firebase API",
    "steps": [
      {"name": "topstories", "method": "GET",
       "url_template": "https://hacker-news.firebaseio.com/v0/topstories.json"},
      {"name": "item", "method": "GET",
       "url_template": "https://hacker-news.firebaseio.com/v0/item/{id}.json",
       "foreach": "top_ids"}
    ],
    "mapper": "hn_firebase_v0"
  },
  "agent": {
    "enabled": true,
    "agent_id": "h/web-surfer-pro",
    "prompt_template": "Open {{site}}. Return the top {{limit}} stories as JSON matching the schema. Fields: rank, title, url, points, hn_url.",
    "answer_schema_ref": "output_schema"
  },
  "health": {
    "min_array_length": {"path": "stories", "min": 1},
    "required_paths": ["stories.0.title", "stories.0.url"],
    "max_latency_ms": 15000
  },
  "compiled_at": "ISO-8601",
  "compile_meta": {"engine": "h-computer-use | mock | manual", "session_id": null,
                   "notes": "Discovered or selected Firebase path for HN"}
}
```

`method` semantics:
- `http` — try http first; agent only on failure (if agent.enabled) or force_path
- `agent` — always H (or mock) unless `force_path=http` and http configured
- `hybrid` — try http, then agent automatically on soft fail

Critical product rule: caching answers ≠ contract. Contract stores **how to fulfill any
valid input**.

## Database schema (SQLite, SQLAlchemy create_all)

```sql
CREATE TABLE workspaces (id TEXT PK, name TEXT NOT NULL, created_at TEXT NOT NULL);

CREATE TABLE workflows (
  id TEXT PK, workspace_id TEXT NOT NULL REFERENCES workspaces(id),
  slug TEXT NOT NULL UNIQUE, title TEXT NOT NULL, site TEXT NOT NULL, goal TEXT NOT NULL,
  input_schema_json TEXT NOT NULL, output_schema_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',      -- active | archived
  active_contract_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);

CREATE TABLE contracts (
  id TEXT PK, workflow_id TEXT NOT NULL REFERENCES workflows(id),
  version INTEGER NOT NULL, status TEXT NOT NULL,   -- draft | active | deprecated
  body_json TEXT NOT NULL, method TEXT NOT NULL,    -- http | agent | hybrid
  created_at TEXT NOT NULL, UNIQUE(workflow_id, version));

CREATE TABLE compile_jobs (
  id TEXT PK, workflow_id TEXT NOT NULL REFERENCES workflows(id),
  status TEXT NOT NULL,       -- pending | running | completed | failed
  engine TEXT NOT NULL,       -- h | mock | manual
  h_session_id TEXT, error TEXT, result_contract_id TEXT,
  created_at TEXT NOT NULL, finished_at TEXT);

CREATE TABLE runs (
  id TEXT PK, workflow_id TEXT NOT NULL REFERENCES workflows(id),
  contract_id TEXT NOT NULL REFERENCES contracts(id),
  input_json TEXT NOT NULL, output_json TEXT, ok INTEGER NOT NULL,
  path TEXT NOT NULL,         -- http | agent | mock
  latency_ms INTEGER NOT NULL, cost_usd REAL, h_session_id TEXT, error TEXT,
  created_at TEXT NOT NULL);

CREATE INDEX idx_runs_workflow ON runs(workflow_id, created_at);
CREATE INDEX idx_contracts_workflow ON contracts(workflow_id, version);
```

On activate contract: previous active → `deprecated`; set `workflows.active_contract_id`.

## HTTP API surface (base http://127.0.0.1:8000)

- `GET /health` → `{"ok": true, "h_mode": "live" | "mock"}`
- `POST /v1/workflows` — body: slug, title, site, goal, input_schema, output_schema
- `GET /v1/workflows`
- `GET /v1/workflows/{id_or_slug}`
- `GET /v1/workflows/{id_or_slug}/contracts`
- `GET /v1/workflows/{id_or_slug}/openapi.json` — single-path OpenAPI 3 fragment for the
  run operation (input schema as request body, output schema as response)
- `POST /v1/workflows/{id_or_slug}/compile` — body:
  `{"engine": "auto", "prefer_http_hints": [...], "activate": true}`
  - engine=auto: use H if HAI_API_KEY set and mock disabled, else mock
  - HN specialization: when site host is news.ycombinator.com (or slug hn-*), attach the
    `hn_firebase_v0` http mapper and set `method=hybrid` (http-first with agent fallback)
  - generic sites: `method=agent`, store agent prompt + schema
  - insert contract version = max+1; activate if requested
  - returns contract + compile job
- `POST /v1/workflows/{id_or_slug}/run` — body:
  `{"input": {...}, "force_path": null|"http"|"agent", "contract_version": null|int}`
  - response: `{"ok": true, "data": {...}, "meta": {"run_id", "contract_id",
    "contract_version", "path", "latency_ms", "cost_usd", "h_session_id", "health_ok"}}`
- `GET /v1/runs/{id}`
- `GET /v1/workflows/{id_or_slug}/runs?limit=20`
- `POST /v1/workflows/{id_or_slug}/recompile` — same as compile; bumps version (manual heal)

## Runtime router algorithm (implement precisely)

```
run(workflow, input, force_path=None):
  contract = requested version or active contract, else 404
  validate input against contract.input_schema (apply defaults)
  order = resolve_path_order(contract.method, force_path)
    # force_path=http  → [http]     (400 if http not configured)
    # force_path=agent → [agent]
    # method=http      → [http, agent] if agent.enabled else [http]
    # method=agent     → [agent] (plus [http] first only if force_path=http)
    # method=hybrid    → [http, agent]
  errors = []
  for path in order:
    try:
      t0 = now()
      data = execute_http(contract, input) or execute_agent(contract, input)
      latency = now() - t0
      validate_output(data, contract.output_schema)   # jsonschema; failure → path fails
      health_ok = check_health(data, contract.health, latency)
      if not health_ok: errors.append((path, "health_failed")); continue
      persist run ok=true; return success(data, path, latency)
    except Exception as e: errors.append((path, e)); continue
  persist run ok=false; return 502 with errors
```

Every run stores `path`. Never silently swap paths without `meta.path`.

## HN Firebase executor (mapper `hn_firebase_v0`)

- `GET https://hacker-news.firebaseio.com/v0/topstories.json` → list of ids
- `GET https://hacker-news.firebaseio.com/v0/item/{id}.json` → {title, url, score, id, ...}

```python
stories = []
for rank, id in enumerate(ids[:limit], start=1):
    item = fetch_item(id)
    stories.append({
        "rank": rank,
        "title": item["title"],
        "url": item.get("url") or f"https://news.ycombinator.com/item?id={id}",
        "points": item.get("score") or 0,
        "hn_url": f"https://news.ycombinator.com/item?id={id}",
    })
return {"stories": stories}
```

Parallel item fetch (asyncio.gather, concurrency cap 10). httpx client reuse (singleton).

## H Computer-Use integration

Live mode (only when HAI_API_KEY set and API_H_MOCK_H=false): `hai_agents.Client`,
`client.run_session(agent=HAI_AGENT, messages=prompt, answer_schema=PydanticModel)`.
Import hai_agents lazily inside the live path — the package may not be installed; never
crash at import time.

Mock mode (default; HAI_API_KEY missing or API_H_MOCK_H=true): `execute_agent` returns
deterministic fake stories after `asyncio.sleep(1.5)` to simulate latency; compile still
creates the contract; `/health` reports `"h_mode": "mock"`. Runs served by the mock report
`path="agent"` in meta (the mock stands in for the agent path; run row may note mock in
compile/engine fields).

Prompt template rules: always include site URL and field list; say "return only data
matching schema; do not invent URLs — if missing use HN item URL"; interpolate input with
safe substitution only ({{var}} replacement, no eval).

cost_usd: 0/None in mock; map from H usage if available else None. Always measure
wall-clock latency_ms. Never log the full HAI_API_KEY.

## Validation and health

- jsonschema against output_schema; failure → path fails
- health checks: `min_array_length` (dotted path), `required_paths` (dotted paths,
  numeric segments index arrays), `max_latency_ms` (fail hard for agent path, warn-log
  only for http path)

## Security (MVP)

- HTTP executor host allowlist: `hacker-news.firebaseio.com` only (SSRF guard). Executor
  must reject any URL whose host is not allowlisted.
- HN item ids must be integers.
- No eval of LLM output. Slug sanitized `^[a-z0-9-]+$`.

## Optimizations to implement now

HTTP-first router; httpx client reuse; parallel HN item fetch (cap 10); no H call when
http succeeds; SQLite WAL (`PRAGMA journal_mode=WAL`); export contract JSON to
`contracts/<slug>-v<version>.json` on activate.

## Seed + demo

`scripts/seed.py`: create default workspace, workflow `hn-top-stories` with the schemas
above, compile engine=auto activate=true, print curl examples.

`scripts/demo_curl.sh`: health → compile → run (http) → run force_path=agent, jq output.

## Static UI (single static/index.html served by FastAPI)

Health/h_mode display, Compile button, Run (http) button, Run force agent button, JSON
viewer, `meta.path` + latency in large text. No React.

## Tests (all offline, no H key)

- test_hn_firebase_mapper with respx (mock Firebase endpoints)
- test_router_prefers_http
- test_force_path_agent uses mock H
- test_schema_validation_fails (invalid output → path failure / run not ok)
- test_ssrf_blocked (non-allowlisted host rejected)

## Acceptance checklist

- uvicorn app.main:app starts with empty DB
- seed creates HN workflow + contract
- run without force_path → meta.path == "http" and ≥1 story
- force_path agent → meta.path == "agent" (mock sleep or live H)
- invalid output fails validation in a unit test
- no Browserbase deps; README explains agent re-trigger caveat
- data/*.db gitignored; pytest passes offline

## README must contain

What is API H; Autobrowse vs API H table; H products used (Computer-Use Agents, not
Browserbase); contract anatomy; when H is called vs not; quickstart (uv, uvicorn, seed,
demo); ascii architecture diagram; caveats (below); future work; pitch snippets.

Caveats for README: not every site has an insta-API (many stay agent); ToS/robots are user
responsibility (HN Firebase is a public API); agent non-determinism (schema validation
mandatory); auth walls/CAPTCHA out of scope; mock mode is offline dev; HN is specialized
for the wow path; wrapper trap (if every request is agent you only built a proxy);
SSRF allowlist; never log HAI_API_KEY.

Pitch snippets: 15s — "H agents can use any website but cost a full browse every time.
API H compiles one run into a versioned contract and serves REST — HTTP when we can, H only
when we must." vs Autobrowse — "Autobrowse graduates a skill for the next agent. We
graduate a contract for any HTTP client." Judge trap ('isn't this caching?') — "Cache
stores answers. Contract stores how to answer for new inputs."

Cost intuition table: http HN 100ms–2s ~$0; agent H 30s–120s task-level cents to dollars
(do not invent exact H pricing).

Ascii architecture for README:

```
┌──────────────────────────────────────────────┐
│  Client (curl / UI / future MCP)             │
└────────────────────┬─────────────────────────┘
                     │ POST /run  POST /compile
                     ▼
┌──────────────────────────────────────────────┐
│  API H (FastAPI)                             │
│  ┌─────────────┐  ┌────────────────────────┐ │
│  │ Compiler    │  │ Runtime Router         │ │
│  │ → contract  │  │ http → agent fallback  │ │
│  └──────┬──────┘  └───────────┬────────────┘ │
│         │                     │              │
│         ▼                     ▼              │
│  ┌────────────┐      ┌──────────────┐        │
│  │ SQLite     │      │ HN Firebase  │        │
│  │ contracts  │      │ (no H)       │        │
│  │ runs       │      └──────────────┘        │
│  └────────────┘      ┌──────────────┐        │
│                      │ H Computer-  │        │
│                      │ Use (compile │        │
│                      │  + agent run)│        │
│                      └──────────────┘        │
└──────────────────────────────────────────────┘
```

Reference links: https://hub.hcompany.ai/computer-use-agents/introduction ,
https://github.com/hcompai/hai-agents-python , https://hcompany.ai/ ,
https://browserbase.com/blog/autobrowse/ (pattern only), https://github.com/HackerNews/API
