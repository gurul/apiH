"""Compiler: one H run (or mock) verifies the goal, then a versioned contract is stored.

H agent = person walking the building; the contract this module emits = the
receptionist window everyone talks to afterwards.
"""

import copy
import json
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app import models, schemas
from app.config import get_settings
from app.services import contract_store, h_client, schema_infer
from app.services.http_executors.base import execute_http
from app.services.http_executors.generated import validate_generated_url
from app.services.validate import validate_output

HN_HOSTS = {"news.ycombinator.com"}

# hostname → known HTTP path (mapper + steps) attached at compile time; method=hybrid.
SPECIALIZATIONS: dict[str, dict] = {
    "news.ycombinator.com": {
        "mapper": "hn_firebase_v0",
        "description": "HN Firebase API",
        "steps": [
            {
                "name": "topstories",
                "method": "GET",
                "url_template": "https://hacker-news.firebaseio.com/v0/topstories.json",
            },
            {
                "name": "item",
                "method": "GET",
                "url_template": "https://hacker-news.firebaseio.com/v0/item/{id}.json",
                "foreach": "top_ids",
            },
        ],
    },
    "wttr.in": {
        "mapper": "wttr_v0",
        "description": "wttr.in JSON weather API",
        "steps": [
            {
                "name": "current",
                "method": "GET",
                "url_template": "https://wttr.in/{city}?format=j1",
            }
        ],
    },
    "openlibrary.org": {
        "mapper": "openlibrary_search_v0",
        "description": "Open Library search API",
        "steps": [
            {
                "name": "search",
                "method": "GET",
                "url_template": "https://openlibrary.org/search.json?q={q}&limit={limit}",
            }
        ],
    },
    "countries.trevorblades.com": {
        "mapper": "graphql_countries_v0",
        "description": "Countries GraphQL API",
        "steps": [
            {
                "name": "countries",
                "method": "POST",
                "url_template": "https://countries.trevorblades.com/",
            }
        ],
    },
}

_HN_PROMPT = (
    "Open {{site}}. Return the top {{limit}} stories as JSON matching the schema. "
    "Fields: rank, title, url, points, hn_url. Return only data matching the schema; "
    "do not invent URLs — if a story URL is missing use the HN item URL."
)


def is_hn(workflow: models.Workflow) -> bool:
    host = urlparse(workflow.site).hostname
    return host in HN_HOSTS or workflow.slug.startswith("hn")


def find_specialization(workflow: models.Workflow) -> dict | None:
    # Hostname only. A slug prefix rule ("hn*") mis-specialized hn.algolia.com
    # workflows onto the Firebase mapper (caught by the hard eval) — slugs lie.
    host = urlparse(workflow.site).hostname
    return SPECIALIZATIONS.get(host)


def _field_names(output_schema: dict) -> list[str]:
    names: list[str] = []
    for prop, sub in (output_schema.get("properties") or {}).items():
        if isinstance(sub, dict) and sub.get("type") == "array":
            item_props = ((sub.get("items") or {}).get("properties")) or {}
            names.extend(item_props or [prop])
        else:
            names.append(prop)
    return names


def _build_health(output_schema: dict) -> dict:
    health: dict = {}
    for prop, sub in (output_schema.get("properties") or {}).items():
        if isinstance(sub, dict) and sub.get("type") == "array":
            health["min_array_length"] = {"path": prop, "min": 1}
            item_required = ((sub.get("items") or {}).get("required")) or []
            health["required_paths"] = [f"{prop}.0.{p}" for p in item_required]
            break
    # Per-path budgets: http warn-logs over 15s; agent hard-fails over 10min (live
    # Computer-Use runs legitimately take minutes — see check_health).
    health["max_latency_ms"] = 15000
    health["max_latency_ms_agent"] = 600000
    return health


def needs_discovery(workflow: models.Workflow) -> bool:
    """True when the workflow was created without schemas (or with empty ones)."""
    output_schema = json.loads(workflow.output_schema_json or "{}")
    return not output_schema.get("properties")


def _discovery_prompt(workflow: models.Workflow, defaults: dict) -> str:
    goal = h_client.render_prompt(workflow.goal, {**defaults, "site": workflow.site})
    return (
        f"Open {workflow.site}. Goal: {goal}. "
        "Achieve the goal once and return the result as a single JSON object whose "
        'top-level keys name the collections (for example {"results": [...]}). '
        "Use consistent field names across items; do not invent URLs — "
        "omit unknown values rather than guessing."
    )


_ROUTE_PLAN_SCHEMA = {
    "type": "object",
    "required": [
        "available",
        "method",
        "url",
        "query_json",
        "body_json",
        "response_path",
        "output_key",
        "notes",
    ],
    "properties": {
        "available": {"type": "boolean"},
        "method": {"type": "string"},
        "url": {"type": "string"},
        "query_json": {"type": "string"},
        "body_json": {"type": "string"},
        "response_path": {"type": "string"},
        "output_key": {"type": "string"},
        "notes": {"type": "string"},
    },
}


async def generate_http_specialization(
    workflow: models.Workflow, hints: list[str]
) -> tuple[dict | None, str | None, str]:
    """Ask H to discover a simple public JSON route and verify it before use."""
    input_schema = json.loads(workflow.input_schema_json)
    output_schema = json.loads(workflow.output_schema_json)
    defaults = schema_infer.input_defaults(input_schema)
    hint_text = "; ".join(hints) if hints else "none"
    prompt = (
        f"Open {workflow.site} and complete this workflow once: {workflow.goal}. "
        "Then identify whether the workflow is backed by one unauthenticated public "
        "JSON GET or POST request that can be replayed directly. Do not guess. "
        "Return available=false unless you can identify the exact HTTPS endpoint. "
        "Use {{input_name}} placeholders in the URL, query_json, or body_json. "
        "query_json and body_json must be JSON object strings. response_path is a "
        "dot-separated path into the response. output_key optionally wraps the selected "
        f"value to match this output schema: {json.dumps(output_schema)}. "
        f"Example inputs: {json.dumps(defaults)}. Developer hints: {hint_text}."
    )
    result = await h_client.run_h_session(prompt, _ROUTE_PLAN_SCHEMA)
    answer = result.answer
    if not answer.get("available"):
        return None, result.session_id, str(answer.get("notes") or "no route found")

    method = str(answer.get("method") or "").upper()
    url = str(answer.get("url") or "")
    if method not in {"GET", "POST"}:
        return None, result.session_id, "agent proposed an unsupported HTTP method"
    try:
        allowed_host = validate_generated_url(url)
        query = json.loads(answer.get("query_json") or "{}")
        body = json.loads(answer.get("body_json") or "{}")
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return None, result.session_id, f"agent route rejected: {exc}"
    if not isinstance(query, dict) or not isinstance(body, dict):
        return None, result.session_id, "agent route query/body must be JSON objects"

    plan = {
        "method": method,
        "url": url,
        "query": query,
        "body": body,
        "response_path": str(answer.get("response_path") or ""),
        "output_key": str(answer.get("output_key") or ""),
    }
    specialization = {
        "mapper": "generated_http_v1",
        "description": "HTTP route generated by H Computer-Use and replay-verified",
        "steps": [{"name": "generated_request", "method": method, "url_template": url}],
        "generated_by": "h-computer-use",
        "allowed_host": allowed_host,
        "plan": plan,
    }
    candidate = build_contract_body(
        workflow,
        engine="h",
        session_id=result.session_id,
        notes="Agent-generated HTTP route candidate",
        specialization=specialization,
    )
    try:
        sample = await execute_http(candidate, defaults)
        validate_output(sample, output_schema)
    except Exception as exc:  # candidate stays off unless replay and schema checks pass
        return None, result.session_id, f"agent route failed verification: {exc}"
    return specialization, result.session_id, str(answer.get("notes") or "verified")


async def discover_schemas(
    workflow: models.Workflow,
) -> tuple[dict, dict, dict, str | None]:
    """One exploration session (H or mock) → (input_schema, output_schema,
    sample_answer, session_id). The sample doubles as the compile probe."""
    input_schema = schema_infer.derive_input_schema(workflow.goal)
    defaults = schema_infer.input_defaults(input_schema)
    result = await h_client.run_h_session(
        _discovery_prompt(workflow, defaults), {"type": "object"}
    )
    sample = result.answer if isinstance(result.answer, dict) else {"results": result.answer}
    return input_schema, schema_infer.infer_json_schema(sample), sample, result.session_id


def build_contract_body(
    workflow: models.Workflow,
    *,
    hn: bool = False,
    engine: str,
    session_id: str | None,
    notes: str,
    sample: dict | None = None,
    specialization: dict | None = None,
) -> dict:
    input_schema = json.loads(workflow.input_schema_json)
    output_schema = json.loads(workflow.output_schema_json)
    if hn and specialization is None:  # backcompat: hn=True means the HN specialization
        specialization = SPECIALIZATIONS["news.ycombinator.com"]
    if specialization is not None and specialization["mapper"] == "hn_firebase_v0":
        prompt = _HN_PROMPT
    else:
        fields = ", ".join(_field_names(output_schema)) or "per output schema"
        prompt = (
            f"Open {{{{site}}}}. Goal: {workflow.goal}. "
            f"Return the result as JSON matching the schema. Fields: {fields}. "
            "Return only data matching the schema; do not invent URLs — "
            "omit unknown values rather than guessing."
        )
    if specialization is not None:
        http_block = {
            "enabled": True,
            "description": specialization["description"],
            "steps": copy.deepcopy(specialization["steps"]),
            "mapper": specialization["mapper"],
            "created_with": specialization.get(
                "created_with", "h-company-computer-use"
            ),
            **(
                {
                    "generated_by": specialization["generated_by"],
                    "allowed_host": specialization["allowed_host"],
                    "plan": copy.deepcopy(specialization["plan"]),
                    "verification": {"replayed": True, "schema_valid": True},
                }
                if specialization.get("generated_by")
                else {}
            ),
        }
    else:
        http_block = {"enabled": False}
    return {
        "id": None,  # id/workflow_id/version finalized by contract_store.insert_contract
        "workflow_id": workflow.id,
        "version": None,
        "status": "draft",
        "title": workflow.title,
        "site": workflow.site,
        "goal": workflow.goal,
        "input_schema": input_schema,
        "output_schema": output_schema,
        "method": "hybrid" if specialization is not None else "agent",
        "http": http_block,
        "agent": {
            "enabled": True,
            "agent_id": get_settings().hai_agent,
            "prompt_template": prompt,
            "answer_schema_ref": "output_schema",
        },
        "health": _build_health(output_schema),
        "compiled_at": models.now_iso(),
        "compile_meta": {
            "engine": "h-computer-use" if engine == "h" else engine,
            "session_id": session_id,
            "notes": notes,
            # Fixture from the discovery run, when one happened.
            **({"sample_answer": sample} if sample is not None else {}),
        },
    }


def _job_out(job: models.CompileJob) -> schemas.CompileJobOut:
    return schemas.CompileJobOut(
        id=job.id,
        workflow_id=job.workflow_id,
        status=job.status,
        engine=job.engine,
        h_session_id=job.h_session_id,
        error=job.error,
        result_contract_id=job.result_contract_id,
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


async def compile_workflow(
    db: Session, workflow: models.Workflow, req: schemas.CompileRequest
) -> schemas.CompileResponse:
    live = get_settings().h_mode == "live"
    notes_extra = ""
    if req.engine == "auto":
        engine = "h" if live else "mock"
    elif req.engine == "h" and not live:
        engine = "mock"
        notes_extra = " (engine 'h' requested but live mode unavailable; fell back to mock)"
    else:
        engine = req.engine

    job = models.CompileJob(
        id=models.new_id(), workflow_id=workflow.id, status="running", engine=engine
    )
    db.add(job)
    db.commit()

    session_id: str | None = None
    route_session_id: str | None = None
    sample: dict | None = None
    if needs_discovery(workflow):
        # The discovery session doubles as the compile probe — one H run, not two.
        try:
            input_schema, output_schema, sample, session_id = await discover_schemas(
                workflow
            )
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = models.now_iso()
            db.commit()
            return schemas.CompileResponse(job=_job_out(job), contract=None)
        workflow.input_schema_json = json.dumps(input_schema)
        workflow.output_schema_json = json.dumps(output_schema)
        workflow.updated_at = models.now_iso()
        db.commit()
        if engine == "mock":
            notes_extra += (
                " (mock discovery — placeholder schema; recompile with live H"
                " for real discovery)"
            )
        else:
            notes_extra += "; schemas discovered from one exploration run"
    elif engine == "h":
        probe = (
            f"Open {workflow.site}. {workflow.goal}. "
            "Return only data matching the schema as JSON; do not invent URLs."
        )
        try:
            result = await h_client.run_h_session(
                probe, json.loads(workflow.output_schema_json)
            )
            session_id = result.session_id
        except Exception as e:
            job.status = "failed"
            job.error = str(e)
            job.finished_at = models.now_iso()
            db.commit()
            return schemas.CompileResponse(job=_job_out(job), contract=None)

    spec = find_specialization(workflow)
    route_note = ""
    if spec is None and engine == "h":
        try:
            spec, route_session_id, route_note = await generate_http_specialization(
                workflow, req.prefer_http_hints
            )
        except Exception as exc:
            route_note = f"agent route generation failed: {exc}"
    if spec is None:
        notes = "Agent-only contract; no verified HTTP path"
        if route_note:
            notes += f" ({route_note})"
    elif spec.get("generated_by"):
        notes = f"Generated and verified HTTP route with H ({route_note})"
    elif spec["mapper"] == "hn_firebase_v0":
        notes = "Selected H Company-assisted Firebase route map for HN"
    else:
        notes = (
            "Selected H Company-assisted HTTP route map via mapper "
            f"{spec['mapper']}"
        )
    notes += notes_extra
    body = build_contract_body(
        workflow,
        engine=engine,
        session_id=session_id,
        notes=notes,
        sample=sample,
        specialization=spec,
    )
    if route_session_id:
        body["compile_meta"]["route_generation_session_id"] = route_session_id
    contract = contract_store.insert_contract(db, workflow, body, method=body["method"])
    if req.activate:
        contract_store.activate_contract(db, workflow, contract)

    job.status = "completed"
    job.h_session_id = session_id
    job.result_contract_id = contract.id
    job.finished_at = models.now_iso()
    db.commit()
    return schemas.CompileResponse(
        job=_job_out(job), contract=contract_store.contract_out(contract)
    )
