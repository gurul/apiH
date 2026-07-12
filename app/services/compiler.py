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

HN_HOSTS = {"news.ycombinator.com"}

_HN_HTTP_BLOCK = {
    "enabled": True,
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
    "mapper": "hn_firebase_v0",
}

_HN_PROMPT = (
    "Open {{site}}. Return the top {{limit}} stories as JSON matching the schema. "
    "Fields: rank, title, url, points, hn_url. Return only data matching the schema; "
    "do not invent URLs — if a story URL is missing use the HN item URL."
)


def is_hn(workflow: models.Workflow) -> bool:
    host = urlparse(workflow.site).hostname
    return host in HN_HOSTS or workflow.slug.startswith("hn")


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
    health["max_latency_ms"] = 15000
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
    hn: bool,
    engine: str,
    session_id: str | None,
    notes: str,
    sample: dict | None = None,
) -> dict:
    input_schema = json.loads(workflow.input_schema_json)
    output_schema = json.loads(workflow.output_schema_json)
    if hn:
        prompt = _HN_PROMPT
    else:
        fields = ", ".join(_field_names(output_schema)) or "per output schema"
        prompt = (
            f"Open {{{{site}}}}. Goal: {workflow.goal}. "
            f"Return the result as JSON matching the schema. Fields: {fields}. "
            "Return only data matching the schema; do not invent URLs — "
            "omit unknown values rather than guessing."
        )
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
        "method": "hybrid" if hn else "agent",
        "http": copy.deepcopy(_HN_HTTP_BLOCK) if hn else {"enabled": False},
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

    hn = is_hn(workflow)
    notes = (
        "Discovered or selected Firebase path for HN"
        if hn
        else "Agent-only contract; no known HTTP path"
    ) + notes_extra
    body = build_contract_body(
        workflow, hn=hn, engine=engine, session_id=session_id, notes=notes, sample=sample
    )
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
