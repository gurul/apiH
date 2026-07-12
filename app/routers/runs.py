import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app import models, schemas
from app.db import get_db

router = APIRouter(prefix="/v1/runs")


def run_record_out(run: models.Run) -> schemas.RunRecordOut:
    return schemas.RunRecordOut(
        id=run.id,
        workflow_id=run.workflow_id,
        contract_id=run.contract_id,
        input=json.loads(run.input_json),
        output=json.loads(run.output_json) if run.output_json else None,
        ok=bool(run.ok),
        path=run.path,
        latency_ms=run.latency_ms,
        cost_usd=run.cost_usd,
        h_session_id=run.h_session_id,
        error=run.error,
        created_at=run.created_at,
    )


@router.get("/{run_id}", response_model=schemas.RunRecordOut)
def get_run(run_id: str, db: Session = Depends(get_db)) -> schemas.RunRecordOut:
    run = db.get(models.Run, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    return run_record_out(run)
