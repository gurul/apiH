"""HN Firebase mapper + SSRF guard. Fully offline — respx intercepts every HTTP call."""

import pytest
import respx

from app.services.http_executors import base
from tests.conftest import TOPSTORIES_URL, item_url

HN_CONTRACT_BODY = {
    "site": "https://news.ycombinator.com",
    "http": {
        "enabled": True,
        "description": "HN Firebase API",
        "steps": [
            {"name": "topstories", "method": "GET", "url_template": TOPSTORIES_URL},
            {
                "name": "item",
                "method": "GET",
                "url_template": "https://hacker-news.firebaseio.com/v0/item/{id}.json",
                "foreach": "top_ids",
            },
        ],
        "mapper": "hn_firebase_v0",
    },
}


@respx.mock
async def test_mapper_maps_ids_to_stories():
    # Only the first `limit` ids get item routes — a fetch of id 104 would blow up unmocked.
    respx.get(TOPSTORIES_URL).respond(json=[101, 102, 103, 104][:3])
    respx.get(item_url(101)).respond(
        json={"id": 101, "title": "First", "url": "https://example.com/a", "score": 321}
    )
    respx.get(item_url(102)).respond(json={"id": 102, "title": "Ask HN: no url", "score": 55})
    respx.get(item_url(103)).respond(
        json={"id": 103, "title": "Third", "url": "https://example.com/c"}
    )

    out = await base.execute_http(HN_CONTRACT_BODY, {"limit": 3})

    stories = out["stories"]
    assert len(stories) == 3
    assert stories[0] == {
        "rank": 1,
        "title": "First",
        "url": "https://example.com/a",
        "points": 321,
        "hn_url": "https://news.ycombinator.com/item?id=101",
    }
    # Missing url falls back to the HN item URL.
    assert stories[1]["rank"] == 2
    assert stories[1]["url"] == "https://news.ycombinator.com/item?id=102"
    assert stories[1]["hn_url"] == "https://news.ycombinator.com/item?id=102"
    assert stories[1]["points"] == 55
    # Missing score falls back to 0.
    assert stories[2]["points"] == 0


@respx.mock(assert_all_called=False)
async def test_mapper_slices_ids_to_limit(respx_mock):
    ids = [201, 202, 203, 204, 205, 206]
    respx_mock.get(TOPSTORIES_URL).respond(json=ids)
    for i in ids:
        respx_mock.get(item_url(i)).respond(
            json={"id": i, "title": f"Story {i}", "url": f"https://example.com/{i}", "score": i}
        )

    out = await base.execute_http(HN_CONTRACT_BODY, {"limit": 2})

    assert [s["rank"] for s in out["stories"]] == [1, 2]
    assert not respx_mock.get(item_url(203)).called


async def test_get_json_blocks_non_allowlisted_host():
    with pytest.raises(base.SSRFBlockedError):
        await base.get_json("https://evil.example.com/x")


async def test_get_json_blocks_non_https_scheme():
    with pytest.raises(base.SSRFBlockedError):
        await base.get_json("http://hacker-news.firebaseio.com/v0/topstories.json")
