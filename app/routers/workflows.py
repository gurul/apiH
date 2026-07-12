import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db
from app.routers.runs import run_record_out
from app.services import compiler, contract_store
from app.services.router import RunFailedError, run_workflow

router = APIRouter(prefix="/v1/workflows")


def workflow_out(wf: models.Workflow) -> schemas.WorkflowOut:
    return schemas.WorkflowOut(
        id=wf.id,
        workspace_id=wf.workspace_id,
        slug=wf.slug,
        title=wf.title,
        site=wf.site,
        goal=wf.goal,
        input_schema=json.loads(wf.input_schema_json),
        output_schema=json.loads(wf.output_schema_json),
        status=wf.status,
        active_contract_id=wf.active_contract_id,
        created_at=wf.created_at,
        updated_at=wf.updated_at,
    )


def _workflow_or_404(db: Session, id_or_slug: str) -> models.Workflow:
    wf = contract_store.get_workflow(db, id_or_slug)
    if wf is None:
        raise HTTPException(status_code=404, detail=f"workflow {id_or_slug!r} not found")
    return wf


@router.post("", response_model=schemas.WorkflowOut, status_code=201)
def create_workflow(
    body: schemas.WorkflowCreate, db: Session = Depends(get_db)
) -> schemas.WorkflowOut:
    if contract_store.get_workflow(db, body.slug) is not None:
        raise HTTPException(status_code=409, detail=f"slug {body.slug!r} already exists")
    workspace = contract_store.get_or_create_default_workspace(db)
    wf = models.Workflow(
        workspace_id=workspace.id,
        slug=body.slug,
        title=body.title,
        site=body.site,
        goal=body.goal,
        input_schema_json=json.dumps(body.input_schema),
        output_schema_json=json.dumps(body.output_schema),
    )
    db.add(wf)
    db.commit()
    return workflow_out(wf)


@router.get("", response_model=list[schemas.WorkflowOut])
def list_workflows(db: Session = Depends(get_db)) -> list[schemas.WorkflowOut]:
    rows = db.execute(
        select(models.Workflow).order_by(models.Workflow.created_at)
    ).scalars().all()
    return [workflow_out(wf) for wf in rows]


@router.get("/{id_or_slug}/contracts", response_model=list[schemas.ContractOut])
def list_contracts(
    id_or_slug: str, db: Session = Depends(get_db)
) -> list[schemas.ContractOut]:
    wf = _workflow_or_404(db, id_or_slug)
    rows = db.execute(
        select(models.Contract)
        .where(models.Contract.workflow_id == wf.id)
        .order_by(models.Contract.version)
    ).scalars().all()
    return [contract_store.contract_out(c) for c in rows]


@router.get("/{id_or_slug}/openapi.json")
def workflow_openapi(id_or_slug: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    wf = _workflow_or_404(db, id_or_slug)
    contract = contract_store.get_active_contract(db, wf)
    if contract is None:
        raise HTTPException(
            status_code=404, detail=f"workflow {wf.slug!r} has no active contract"
        )
    body = json.loads(contract.body_json)
    meta_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "contract_id": {"type": "string"},
            "contract_version": {"type": "integer"},
            "path": {"type": "string", "enum": ["http", "agent", "mock"]},
            "latency_ms": {"type": "integer"},
            "cost_usd": {"type": ["number", "null"]},
            "h_session_id": {"type": ["string", "null"]},
            "health_ok": {"type": "boolean"},
        },
    }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": f"API H — {wf.title}",
            "version": str(contract.version),
            "description": wf.goal,
        },
        "paths": {
            f"/v1/workflows/{wf.slug}/run": {
                "post": {
                    "operationId": f"run_{wf.slug.replace('-', '_')}",
                    "summary": wf.title,
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "input": body["input_schema"],
                                        "force_path": {
                                            "type": ["string", "null"],
                                            "enum": ["http", "agent"],
                                        },
                                        "contract_version": {
                                            "type": ["integer", "null"]
                                        },
                                    },
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Run result",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["ok", "data", "meta"],
                                        "properties": {
                                            "ok": {"type": "boolean"},
                                            "data": body["output_schema"],
                                            "meta": meta_schema,
                                        },
                                    }
                                }
                            },
                        }
                    },
                }
            }
        },
    }


@router.post("/{id_or_slug}/compile", response_model=schemas.CompileResponse)
@router.post("/{id_or_slug}/recompile", response_model=schemas.CompileResponse)
async def compile_workflow(
    id_or_slug: str, body: schemas.CompileRequest, db: Session = Depends(get_db)
) -> schemas.CompileResponse:
    wf = _workflow_or_404(db, id_or_slug)
    return await compiler.compile_workflow(db, wf, body)


@router.post("/{id_or_slug}/run", response_model=schemas.RunResponse)
async def run(
    id_or_slug: str, body: schemas.RunRequest, db: Session = Depends(get_db)
) -> schemas.RunResponse | JSONResponse:
    wf = _workflow_or_404(db, id_or_slug)
    try:
        return await run_workflow(db, wf, body)
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except RunFailedError as e:
        return JSONResponse(
            status_code=502,
            content={"ok": False, "errors": e.errors, "run_id": e.run_id},
        )
    except ValueError as e:  # InputValidationError, PathUnavailableError
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/{id_or_slug}/runs", response_model=list[schemas.RunRecordOut])
def list_runs(
    id_or_slug: str, limit: int = 20, db: Session = Depends(get_db)
) -> list[schemas.RunRecordOut]:
    wf = _workflow_or_404(db, id_or_slug)
    rows = db.execute(
        select(models.Run)
        .where(models.Run.workflow_id == wf.id)
        .order_by(models.Run.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [run_record_out(r) for r in rows]


# Catch-all last so literal sub-paths above win.
@router.get("/{id_or_slug}", response_model=schemas.WorkflowOut)
def get_workflow(id_or_slug: str, db: Session = Depends(get_db)) -> schemas.WorkflowOut:
    return workflow_out(_workflow_or_404(db, id_or_slug))
