"""Test env must be pinned before ANY app import — config caches settings at import."""

import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["API_H_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["API_H_MOCK_H"] = "true"
os.environ["HAI_API_KEY"] = ""
os.environ["API_H_CONTRACTS_DIR"] = f"{_tmp}/contracts"  # keep exports out of the repo

import json

import pytest

INPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {"limit": {"type": "integer", "default": 5}},
}

OUTPUT_SCHEMA: dict = {
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
                    "hn_url": {"type": "string"},
                },
            },
        }
    },
}

TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"


def item_url(item_id: int) -> str:
    return f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"


def story_items(ids: list[int]) -> dict[int, dict]:
    return {
        i: {"id": i, "title": f"Story {i}", "url": f"https://example.com/{i}", "score": 100 + i}
        for i in ids
    }


def mock_firebase(router, ids: list[int], items: dict[int, dict]) -> None:
    """Register Firebase routes on a respx router (or the respx module itself)."""
    router.get(TOPSTORIES_URL).respond(json=ids)
    for item_id, item in items.items():
        router.get(item_url(item_id)).respond(json=item)


def create_hn_workflow(
    db,
    *,
    slug: str = "hn-top-stories",
    output_schema: dict | None = None,
    agent_enabled: bool = True,
):
    """HN workflow + active hybrid contract built through the real services (no raw SQL)."""
    from app import models
    from app.services import compiler, contract_store

    ws = contract_store.get_or_create_default_workspace(db)
    wf = models.Workflow(
        workspace_id=ws.id,
        slug=slug,
        title="Hacker News top stories",
        site="https://news.ycombinator.com",
        goal="Return top N front-page stories with rank, title, url, points",
        input_schema_json=json.dumps(INPUT_SCHEMA),
        output_schema_json=json.dumps(output_schema or OUTPUT_SCHEMA),
    )
    db.add(wf)
    db.commit()
    body = compiler.build_contract_body(
        wf, hn=True, engine="mock", session_id=None, notes="test fixture"
    )
    if not agent_enabled:
        body["agent"]["enabled"] = False
    contract = contract_store.insert_contract(db, wf, body, method=body["method"])
    contract_store.activate_contract(db, wf, contract)
    db.commit()
    return wf


@pytest.fixture(autouse=True)
def _fresh_db():
    from app import models  # noqa: F401  (register mappings)
    from app.db import Base, engine

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def db():
    from app.db import SessionLocal

    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def fast_agent(monkeypatch):
    """No-op the mock agent's simulated latency (h_client's asyncio.sleep)."""
    from app.services import h_client

    async def _nosleep(*_args, **_kwargs) -> None:
        return None

    monkeypatch.setattr(h_client.asyncio, "sleep", _nosleep)
