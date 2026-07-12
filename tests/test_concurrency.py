"""20 concurrent /run calls on the HN hybrid contract — ASGITransport + respx Firebase."""

import asyncio

import httpx
import respx

from tests.conftest import create_hn_workflow, mock_firebase, story_items

N_RUNS = 20


@respx.mock
async def test_twenty_concurrent_runs_all_http_all_persisted(db):
    import app.services.http_executors  # noqa: F401  (mapper registration; no lifespan here)
    from app import models
    from app.main import app

    wf = create_hn_workflow(db)
    ids = [401, 402, 403]
    mock_firebase(respx, ids, story_items(ids))

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        responses = await asyncio.gather(
            *(
                client.post(f"/v1/workflows/{wf.slug}/run", json={"input": {"limit": 3}})
                for _ in range(N_RUNS)
            )
        )

    assert [r.status_code for r in responses] == [200] * N_RUNS
    for resp in responses:
        body = resp.json()
        assert body["ok"] is True
        assert body["meta"]["path"] == "http"
        assert len(body["data"]["stories"]) == 3

    db.expire_all()
    rows = db.query(models.Run).filter(models.Run.workflow_id == wf.id).all()
    assert len(rows) == N_RUNS
    assert all(row.ok == 1 for row in rows)
    assert all(row.path == "http" for row in rows)
