"""hn_firebase_v0 mapper — HN Firebase API (SPEC §HN Firebase executor)."""

import asyncio

from app.services.http_executors.base import get_json, register_mapper

TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM_URL_TEMPLATE = "https://hacker-news.firebaseio.com/v0/item/{id}.json"

FEED_URLS: dict[str | None, str] = {
    None: TOPSTORIES_URL,
    "top": TOPSTORIES_URL,
    "ask": "https://hacker-news.firebaseio.com/v0/askstories.json",
    "show": "https://hacker-news.firebaseio.com/v0/showstories.json",
}

_FETCH_CONCURRENCY = 10


@register_mapper("hn_firebase_v0")
async def run(contract_body: dict, input: dict) -> dict:
    limit = int(input.get("limit", 5))
    feed = input.get("feed")
    if feed not in FEED_URLS:
        raise ValueError(f"unknown HN feed {feed!r}; expected one of top, ask, show")

    ids_raw = await get_json(FEED_URLS[feed])
    if not isinstance(ids_raw, list):
        raise ValueError("HN feed endpoint did not return a list of ids")
    # ids must be integers before URL interpolation (SSRF/injection guard)
    ids = [int(item_id) for item_id in ids_raw[:limit]]

    semaphore = asyncio.Semaphore(_FETCH_CONCURRENCY)

    async def fetch_item(item_id: int) -> object:
        async with semaphore:
            return await get_json(ITEM_URL_TEMPLATE.format(id=item_id))

    items = await asyncio.gather(*(fetch_item(item_id) for item_id in ids))

    stories: list[dict] = []
    for rank, (item_id, item) in enumerate(zip(ids, items), start=1):
        if not isinstance(item, dict):
            raise ValueError(f"item {item_id} returned no data")
        hn_url = f"https://news.ycombinator.com/item?id={item_id}"
        stories.append(
            {
                "rank": rank,
                "title": item["title"],
                "url": item.get("url") or hn_url,
                "points": item.get("score") or 0,
                "hn_url": hn_url,
            }
        )
    return {"stories": stories}
