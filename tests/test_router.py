"""Runtime router path selection through the HTTP API. Offline — respx + mock H."""

import respx

from app.services import h_client
from tests.conftest import create_hn_workflow, mock_firebase, story_items


@respx.mock
def test_router_prefers_http_on_hybrid(client, db, monkeypatch):
    wf = create_hn_workflow(db)
    ids = [201, 202, 203]
    mock_firebase(respx, ids, story_items(ids))

    agent_calls: list = []

    async def _spy(*args, **kwargs):
        agent_calls.append(args)
        raise AssertionError("agent path must not run when http succeeds")

    # execute_agent funnels through run_h_session, so this spy catches any agent use
    # regardless of how the router imported it.
    monkeypatch.setattr(h_client, "run_h_session", _spy)

    resp = client.post(f"/v1/workflows/{wf.slug}/run", json={"input": {"limit": 3}})

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["meta"]["path"] == "http"
    assert body["meta"]["health_ok"] is True
    assert len(body["data"]["stories"]) == 3
    assert agent_calls == []


@respx.mock
def test_force_path_agent_uses_mock_h(client, db, fast_agent):
    # No respx routes registered: any HTTP escape raises, proving the agent path ran.
    wf = create_hn_workflow(db)

    resp = client.post(
        f"/v1/workflows/{wf.slug}/run",
        json={"input": {"limit": 3}, "force_path": "agent"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["meta"]["path"] == "agent"
    assert body["meta"]["cost_usd"] == 0
    stories = body["data"]["stories"]
    assert len(stories) >= 1
    assert all("Mock HN story" in s["title"] for s in stories)
