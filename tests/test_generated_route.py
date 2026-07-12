"""generate_http_specialization end-to-end: captured traffic → candidates → matrix
replay → verified contract. Offline — mock H answer + respx-intercepted replays."""

import json

import respx

from app import models
from app.services import compiler, h_client

ITEMS_URL = "https://api.example.com/v1/items"

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id"],
                "properties": {"id": {"type": "integer"}},
            },
        }
    },
}

INPUT_SCHEMA = {
    "type": "object",
    "properties": {"limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 30}},
}


def _workflow() -> models.Workflow:
    wf = models.Workflow(
        slug="example-items",
        title="Example items",
        site="https://example.com",
        goal="Return the top {{limit}} items",
        input_schema_json=json.dumps(INPUT_SCHEMA),
        output_schema_json=json.dumps(OUTPUT_SCHEMA),
    )
    wf.id = "wf-test"
    return wf


def _answer(candidates: list[dict]) -> dict:
    captured = [
        {"method": "GET", "url": ITEMS_URL, "content_type": "application/json", "status": 200}
    ]
    return {
        "available": True,
        "captured_json": json.dumps(captured),
        "candidates_json": json.dumps(candidates),
        "method": "",
        "url": "",
        "query_json": "",
        "body_json": "",
        "response_path": "",
        "output_key": "",
        "notes": "captured live",
    }


def _patch_h(monkeypatch, answer: dict) -> None:
    async def fake(_prompt, _schema):
        return h_client.HResult(answer=answer, session_id="sess-1", cost_usd=0.0, engine="h")

    monkeypatch.setattr(h_client, "run_h_session", fake)


@respx.mock
async def test_route_graduates_when_all_inputs_replay(monkeypatch):
    respx.get(ITEMS_URL).respond(json=[{"id": 1}, {"id": 2}])
    _patch_h(
        monkeypatch,
        _answer([{"method": "GET", "url": ITEMS_URL, "query": {"limit": "{{limit}}"}, "output_key": "items"}]),
    )

    spec, session_id, note = await compiler.generate_http_specialization(_workflow(), [])

    assert spec is not None
    assert session_id == "sess-1"
    assert spec["generated_by"] == "h-computer-use"
    assert spec["allowed_host"] == "api.example.com"
    # Evidence preserved (item 5).
    assert spec["evidence"][0]["url"] == ITEMS_URL
    # Verified across the whole input matrix, not one default replay (item 3).
    verification = spec["verification"]
    assert verification["input_count"] >= 3
    assert all(r["ok"] and r["schema_valid"] for r in verification["replays"])
    assert {r["input"]["limit"] for r in verification["replays"]} >= {1, 5, 30}
    assert "verified over" in note


@respx.mock
async def test_evidence_and_replays_persist_into_contract_body(monkeypatch):
    respx.get(ITEMS_URL).respond(json=[{"id": 1}])
    _patch_h(
        monkeypatch,
        _answer([{"method": "GET", "url": ITEMS_URL, "query": {"limit": "{{limit}}"}, "output_key": "items"}]),
    )

    spec, _, _ = await compiler.generate_http_specialization(_workflow(), [])
    body = compiler.build_contract_body(
        _workflow(), engine="h", session_id="sess-1", notes="n", specialization=spec
    )

    http_block = body["http"]
    assert http_block["evidence"][0]["host"] == "api.example.com"
    assert http_block["verification"]["replayed"] is True
    assert len(http_block["verification"]["replays"]) == len(spec["verification"]["replays"])
    # Whole contract must be JSON-serializable for storage/export.
    json.dumps(body)


@respx.mock
async def test_no_route_when_schema_mismatch_on_every_candidate(monkeypatch):
    # Endpoint returns an object, not the array the schema requires → all replays fail.
    respx.get(ITEMS_URL).respond(json={"wrong": 1})
    _patch_h(
        monkeypatch,
        _answer([{"method": "GET", "url": ITEMS_URL, "query": {"limit": "{{limit}}"}, "output_key": "items"}]),
    )

    spec, session_id, note = await compiler.generate_http_specialization(_workflow(), [])

    assert spec is None
    assert session_id == "sess-1"
    assert "failed replay" in note


async def test_available_false_returns_no_route(monkeypatch):
    answer = _answer([])
    answer["available"] = False
    answer["notes"] = "site is a JS SPA with no public JSON route"
    _patch_h(monkeypatch, answer)

    spec, _, note = await compiler.generate_http_specialization(_workflow(), [])

    assert spec is None
    assert "JS SPA" in note


async def test_no_candidates_in_capture_returns_no_route(monkeypatch):
    # available=true but candidates_json empty and no JSON requests captured.
    answer = {
        "available": True,
        "captured_json": json.dumps(
            [{"method": "GET", "url": "https://cdn.example.com/a.png", "content_type": "image/png"}]
        ),
        "candidates_json": "[]",
        "method": "",
        "url": "",
        "query_json": "",
        "body_json": "",
        "response_path": "",
        "output_key": "",
        "notes": "only static assets",
    }
    _patch_h(monkeypatch, answer)

    spec, _, note = await compiler.generate_http_specialization(_workflow(), [])

    assert spec is None
    assert "no evidence-backed" in note
