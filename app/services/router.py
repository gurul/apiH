"""Runtime router — SPEC §Runtime router algorithm. HTTP when we can, H when we must."""

import json
import time

from sqlalchemy.orm import Session

from app import models, schemas
from app.services import contract_store
from app.services.h_client import execute_agent
from app.services.http_executors.base import execute_http
from app.services.validate import check_health, validate_input, validate_output


class PathUnavailableError(ValueError):
    """force_path names a path the contract doesn't have configured/enabled."""


class RunFailedError(Exception):
    def __init__(self, run_id: str, contract: models.Contract, errors: list[dict]):
        super().__init__(f"all paths failed for run {run_id}")
        self.run_id = run_id
        self.contract = contract
        self.errors = errors


def resolve_path_order(
    method: str,
    force_path: str | None,
    http_enabled: bool,
    agent_enabled: bool,
) -> list[str]:
    if force_path == "http":
        if not http_enabled:
            raise PathUnavailableError("http path not configured for this contract")
        return ["http"]
    if force_path == "agent":
        if not agent_enabled:
            raise PathUnavailableError("agent path not enabled for this contract")
        return ["agent"]

    if method == "http":
        order = ["http"] if http_enabled else []
        if agent_enabled:
            order.append("agent")
    elif method == "agent":
        order = ["agent"] if agent_enabled else []
    elif method == "hybrid":
        order = [
            p for p, on in (("http", http_enabled), ("agent", agent_enabled)) if on
        ]
    else:
        raise PathUnavailableError(f"unknown contract method: {method!r}")

    if not order:
        raise PathUnavailableError(
            f"no executable path for method={method!r} "
            f"(http_enabled={http_enabled}, agent_enabled={agent_enabled})"
        )
    return order


async def run_workflow(
    db: Session, workflow: models.Workflow, req: schemas.RunRequest
) -> schemas.RunResponse:
    if req.contract_version is not None:
        contract = contract_store.get_contract_by_version(
            db, workflow.id, req.contract_version
        )
    else:
        contract = contract_store.get_active_contract(db, workflow)
    if contract is None:
        raise LookupError(
            f"no contract for workflow {workflow.slug!r}"
            + (f" version {req.contract_version}" if req.contract_version else "")
        )

    body = json.loads(contract.body_json)
    validated_input = validate_input(req.input, body["input_schema"])

    http_enabled = bool(body.get("http", {}).get("enabled"))
    agent_enabled = bool(body.get("agent", {}).get("enabled"))
    order = resolve_path_order(
        contract.method, req.force_path, http_enabled, agent_enabled
    )

    errors: list[dict] = []
    total_t0 = time.perf_counter()

    for path in order:
        session_id: str | None = None
        cost_usd: float | None = None
        t0 = time.perf_counter()
        try:
            if path == "http":
                data = await execute_http(body, validated_input)
            else:
                result = await execute_agent(body, validated_input)
                data = result.answer
                session_id = result.session_id
                cost_usd = result.cost_usd
            latency_ms = int((time.perf_counter() - t0) * 1000)

            validate_output(data, body["output_schema"])
            if not check_health(data, body.get("health"), latency_ms, path):
                errors.append({"path": path, "error": "health_failed"})
                continue

            run = models.Run(
                workflow_id=workflow.id,
                contract_id=contract.id,
                input_json=json.dumps(validated_input),
                output_json=json.dumps(data),
                ok=1,
                path=path,
                latency_ms=latency_ms,
                cost_usd=cost_usd,
                h_session_id=session_id,
            )
            db.add(run)
            db.commit()
            return schemas.RunResponse(
                ok=True,
                data=data,
                meta=schemas.RunMeta(
                    run_id=run.id,
                    contract_id=contract.id,
                    contract_version=contract.version,
                    path=path,
                    latency_ms=latency_ms,
                    cost_usd=cost_usd,
                    h_session_id=session_id,
                    health_ok=True,
                ),
            )
        except Exception as e:  # noqa: BLE001 — any path failure moves to the next path
            errors.append({"path": path, "error": f"{type(e).__name__}: {e}"})
            continue

    total_latency_ms = int((time.perf_counter() - total_t0) * 1000)
    run = models.Run(
        workflow_id=workflow.id,
        contract_id=contract.id,
        input_json=json.dumps(validated_input),
        output_json=None,
        ok=0,
        path=order[-1],
        latency_ms=total_latency_ms,
        cost_usd=None,
        h_session_id=None,
        error=json.dumps(errors),
    )
    db.add(run)
    db.commit()
    raise RunFailedError(run.id, contract, errors)
