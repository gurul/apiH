"""Contract persistence: versioning, activation, best-effort JSON export."""

import json
import os
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models, schemas

_EXPORT_DIR = Path(
    os.environ.get(
        "API_H_CONTRACTS_DIR", Path(__file__).resolve().parents[2] / "contracts"
    )
)


def get_or_create_default_workspace(db: Session) -> models.Workspace:
    ws = db.execute(
        select(models.Workspace).where(models.Workspace.name == "default")
    ).scalar_one_or_none()
    if ws is None:
        ws = models.Workspace(id=models.new_id(), name="default")
        db.add(ws)
        db.commit()
    return ws


def get_workflow(db: Session, id_or_slug: str) -> models.Workflow | None:
    wf = db.get(models.Workflow, id_or_slug)
    if wf is None:
        wf = db.execute(
            select(models.Workflow).where(models.Workflow.slug == id_or_slug)
        ).scalar_one_or_none()
    return wf


def next_version(db: Session, workflow_id: str) -> int:
    current = db.execute(
        select(func.max(models.Contract.version)).where(
            models.Contract.workflow_id == workflow_id
        )
    ).scalar()
    return (current or 0) + 1


def insert_contract(
    db: Session,
    workflow: models.Workflow,
    body: dict,
    method: str,
    status: str = "draft",
) -> models.Contract:
    contract = models.Contract(
        id=models.new_id(),
        workflow_id=workflow.id,
        version=next_version(db, workflow.id),
        status=status,
        method=method,
        body_json="",
    )
    body = {
        **body,
        "id": contract.id,
        "workflow_id": workflow.id,
        "version": contract.version,
        "status": status,
    }
    contract.body_json = json.dumps(body)
    db.add(contract)
    db.commit()
    return contract


def activate_contract(
    db: Session, workflow: models.Workflow, contract: models.Contract
) -> None:
    previous = (
        db.execute(
            select(models.Contract).where(
                models.Contract.workflow_id == workflow.id,
                models.Contract.status == "active",
                models.Contract.id != contract.id,
            )
        )
        .scalars()
        .all()
    )
    for prev in previous:
        prev.status = "deprecated"
    contract.status = "active"
    body = json.loads(contract.body_json)
    body["status"] = "active"
    contract.body_json = json.dumps(body)
    workflow.active_contract_id = contract.id
    workflow.updated_at = models.now_iso()
    db.commit()

    try:  # export is best-effort; never fail activation on IO
        _EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        path = _EXPORT_DIR / f"{workflow.slug}-v{contract.version}.json"
        path.write_text(json.dumps(body, indent=2))
    except OSError:
        pass


def get_active_contract(
    db: Session, workflow: models.Workflow
) -> models.Contract | None:
    if workflow.active_contract_id:
        contract = db.get(models.Contract, workflow.active_contract_id)
        if contract is not None:
            return contract
    return db.execute(
        select(models.Contract)
        .where(
            models.Contract.workflow_id == workflow.id,
            models.Contract.status == "active",
        )
        .order_by(models.Contract.version.desc())
    ).scalars().first()


def get_contract_by_version(
    db: Session, workflow_id: str, version: int
) -> models.Contract | None:
    return db.execute(
        select(models.Contract).where(
            models.Contract.workflow_id == workflow_id,
            models.Contract.version == version,
        )
    ).scalar_one_or_none()


def contract_out(c: models.Contract) -> schemas.ContractOut:
    return schemas.ContractOut(
        id=c.id,
        workflow_id=c.workflow_id,
        version=c.version,
        status=c.status,
        method=c.method,
        body=json.loads(c.body_json),
        created_at=c.created_at,
    )
