"""Pydantic API schemas — the request/response contract for every router."""

import re
from typing import Any, Literal

from pydantic import BaseModel, field_validator

SLUG_RE = re.compile(r"^[a-z0-9-]+$")

PathName = Literal["http", "agent"]


class WorkflowCreate(BaseModel):
    slug: str
    title: str
    site: str
    goal: str  # may contain {{var}} placeholders — they become run inputs on discovery
    # Omit both schemas to let compile DISCOVER them from one H exploration run.
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None

    @field_validator("slug")
    @classmethod
    def _slug_ok(cls, v: str) -> str:
        if not SLUG_RE.match(v):
            raise ValueError("slug must match ^[a-z0-9-]+$")
        return v


class WorkflowOut(BaseModel):
    id: str
    workspace_id: str
    slug: str
    title: str
    site: str
    goal: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    status: str
    active_contract_id: str | None
    created_at: str
    updated_at: str


class ContractOut(BaseModel):
    id: str
    workflow_id: str
    version: int
    status: str
    method: str
    body: dict[str, Any]  # full contract document (parsed body_json)
    created_at: str


class CompileRequest(BaseModel):
    engine: Literal["auto", "h", "mock"] = "auto"
    prefer_http_hints: list[str] = []
    activate: bool = True


class CompileJobOut(BaseModel):
    id: str
    workflow_id: str
    status: str
    engine: str
    h_session_id: str | None
    error: str | None
    result_contract_id: str | None
    created_at: str
    finished_at: str | None


class CompileResponse(BaseModel):
    job: CompileJobOut
    contract: ContractOut | None


class RunRequest(BaseModel):
    input: dict[str, Any] = {}
    force_path: PathName | None = None
    contract_version: int | None = None


class RunMeta(BaseModel):
    run_id: str
    contract_id: str
    contract_version: int
    path: str  # http | agent | mock — impossible to miss
    latency_ms: int
    cost_usd: float | None
    h_session_id: str | None
    health_ok: bool


class RunResponse(BaseModel):
    ok: bool
    data: dict[str, Any] | None
    meta: RunMeta


class RunRecordOut(BaseModel):
    id: str
    workflow_id: str
    contract_id: str
    input: dict[str, Any]
    output: dict[str, Any] | None
    ok: bool
    path: str
    latency_ms: int
    cost_usd: float | None
    h_session_id: str | None
    error: str | None
    created_at: str


class HealthOut(BaseModel):
    ok: bool
    h_mode: Literal["live", "mock"]
