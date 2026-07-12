"""graphql_countries_v0 mapper — countries.trevorblades.com GraphQL API."""

import re

from app.services.http_executors.base import post_json, register_mapper

COUNTRIES_URL = "https://countries.trevorblades.com/"

_CONTINENT_RE = re.compile(r"^[A-Z]{2}$")

_QUERY = "query($c: ID!){ continent(code:$c){ countries { name } } }"


@register_mapper("graphql_countries_v0")
async def run(contract_body: dict, input: dict) -> dict:
    code = input.get("continent", "EU")
    if not isinstance(code, str) or not _CONTINENT_RE.match(code):
        raise ValueError(f"invalid continent code {code!r}; expected ^[A-Z]{{2}}$")
    limit = max(1, min(20, int(input.get("limit", 5))))

    data = await post_json(COUNTRIES_URL, {"query": _QUERY, "variables": {"c": code}})
    if not isinstance(data, dict):
        raise ValueError("countries GraphQL endpoint did not return a JSON object")
    continent = (data.get("data") or {}).get("continent")
    if not continent:
        raise ValueError(f"continent {code!r} not found")
    names = [c["name"] for c in continent.get("countries") or []]
    return {"countries": names[:limit]}
