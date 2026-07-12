"""SQLAlchemy models — mirrors docs/SPEC.md §Database schema exactly."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Float, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    workspace_id: Mapped[str] = mapped_column(Text, ForeignKey("workspaces.id"))
    slug: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    site: Mapped[str] = mapped_column(Text)
    goal: Mapped[str] = mapped_column(Text)
    input_schema_json: Mapped[str] = mapped_column(Text)
    output_schema_json: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, default="active")  # active | archived
    active_contract_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    updated_at: Mapped[str] = mapped_column(Text, default=now_iso)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version"),
        Index("idx_contracts_workflow", "workflow_id", "version"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(Text, ForeignKey("workflows.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text)  # draft | active | deprecated
    body_json: Mapped[str] = mapped_column(Text)  # full contract document
    method: Mapped[str] = mapped_column(Text)  # http | agent | hybrid
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)


class CompileJob(Base):
    __tablename__ = "compile_jobs"

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(Text, ForeignKey("workflows.id"))
    status: Mapped[str] = mapped_column(Text)  # pending | running | completed | failed
    engine: Mapped[str] = mapped_column(Text)  # h | mock | manual
    h_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_contract_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
    finished_at: Mapped[str | None] = mapped_column(Text, nullable=True)


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (Index("idx_runs_workflow", "workflow_id", "created_at"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True, default=new_id)
    workflow_id: Mapped[str] = mapped_column(Text, ForeignKey("workflows.id"))
    contract_id: Mapped[str] = mapped_column(Text, ForeignKey("contracts.id"))
    input_json: Mapped[str] = mapped_column(Text)
    output_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    ok: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)  # http | agent | mock
    latency_ms: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    h_session_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(Text, default=now_iso)
