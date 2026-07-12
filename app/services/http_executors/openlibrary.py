"""openlibrary_search_v0 mapper — Open Library search API."""

from urllib.parse import quote_plus

from app.services.http_executors.base import get_json, register_mapper


@register_mapper("openlibrary_search_v0")
async def run(contract_body: dict, input: dict) -> dict:
    q = input.get("q", "")
    if not isinstance(q, str) or not q:
        raise ValueError("input 'q' must be a non-empty string")
    limit = max(1, min(20, int(input.get("limit", 5))))

    data = await get_json(
        f"https://openlibrary.org/search.json?q={quote_plus(q)}&limit={limit}"
    )
    if not isinstance(data, dict):
        raise ValueError("openlibrary.org did not return a JSON object")
    works: list[dict] = []
    for doc in (data.get("docs") or [])[:limit]:
        works.append(
            {
                "title": doc["title"],
                "authors": doc.get("author_name") or [],
                "year": doc.get("first_publish_year"),  # int | None
                "key": doc["key"],
            }
        )
    return {"works": works}
