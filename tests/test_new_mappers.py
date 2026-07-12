"""New mappers (EVAL-SPEC) + widened SSRF allowlist. Fully offline — respx everywhere."""

import json

import pytest
import respx

from app.services.http_executors import base
from tests.conftest import item_url

WTTR_SITE = "https://wttr.in"
OPENLIBRARY_SITE = "https://openlibrary.org"
COUNTRIES_URL = "https://countries.trevorblades.com/"

EXPECTED_ALLOWED_HOSTS = {
    "hacker-news.firebaseio.com",
    "wttr.in",
    "openlibrary.org",
    "countries.trevorblades.com",
}


def contract_body(mapper: str, site: str) -> dict:
    return {"site": site, "http": {"enabled": True, "mapper": mapper}}


# ── wttr_v0 ────────────────────────────────────────────────────────────────────


def wttr_payload(temp: str = "21", humidity: str = "60", desc: str = "Sunny") -> dict:
    return {
        "current_condition": [
            {"temp_C": temp, "humidity": humidity, "weatherDesc": [{"value": desc}]}
        ]
    }


@respx.mock
async def test_wttr_maps_current_condition():
    respx.get("https://wttr.in/London?format=j1").respond(json=wttr_payload())

    out = await base.execute_http(contract_body("wttr_v0", WTTR_SITE), {"city": "London"})

    assert out == {"temp_C": "21", "humidity": "60", "weather_desc": "Sunny"}


@respx.mock
async def test_wttr_defaults_to_london():
    route = respx.get("https://wttr.in/London?format=j1").respond(json=wttr_payload())

    out = await base.execute_http(contract_body("wttr_v0", WTTR_SITE), {})

    assert route.called
    assert out["weather_desc"] == "Sunny"


@respx.mock
async def test_wttr_quotes_city_in_url():
    route = respx.get("https://wttr.in/New%20York?format=j1").respond(
        json=wttr_payload(desc="Cloudy")
    )

    out = await base.execute_http(contract_body("wttr_v0", WTTR_SITE), {"city": "New York"})

    assert route.called
    assert out["weather_desc"] == "Cloudy"


# NB: "Paris\n" is deliberately absent — the spec regex ^...$ admits a trailing
# newline under Python's `$` semantics, so it is not a contract violation.
@pytest.mark.parametrize("city", ["Lond/on", "x" * 41, "", "Nice;rm -rf"])
async def test_wttr_invalid_city_raises_before_network(city: str):
    # Zero respx routes: any escaped HTTP call would raise respx's error, not ValueError.
    with respx.mock:
        with pytest.raises(ValueError):
            await base.execute_http(contract_body("wttr_v0", WTTR_SITE), {"city": city})


# ── openlibrary_search_v0 ─────────────────────────────────────────────────────


@respx.mock
async def test_openlibrary_maps_docs_to_works():
    respx.get(
        "https://openlibrary.org/search.json",
        params={"q": "foundation asimov", "limit": "5"},
    ).respond(
        json={
            "docs": [
                {
                    "title": "Foundation",
                    "author_name": ["Isaac Asimov"],
                    "first_publish_year": 1951,
                    "key": "/works/OL46125W",
                },
                {"title": "Mystery doc", "key": "/works/OL1W"},
            ]
        }
    )

    out = await base.execute_http(
        contract_body("openlibrary_search_v0", OPENLIBRARY_SITE),
        {"q": "foundation asimov", "limit": 5},
    )

    assert out["works"][0] == {
        "title": "Foundation",
        "authors": ["Isaac Asimov"],
        "year": 1951,
        "key": "/works/OL46125W",
    }
    # Missing author_name/first_publish_year fall back to []/None.
    assert out["works"][1]["authors"] == []
    assert out["works"][1]["year"] is None


@respx.mock
async def test_openlibrary_clamps_limit_to_20():
    route = respx.get(
        "https://openlibrary.org/search.json", params={"limit": "20"}
    ).respond(json={"docs": []})

    out = await base.execute_http(
        contract_body("openlibrary_search_v0", OPENLIBRARY_SITE),
        {"q": "dune", "limit": 99},
    )

    assert route.called
    assert out["works"] == []


async def test_openlibrary_empty_query_raises_before_network():
    with respx.mock:
        with pytest.raises(ValueError):
            await base.execute_http(
                contract_body("openlibrary_search_v0", OPENLIBRARY_SITE), {"q": ""}
            )


# ── graphql_countries_v0 ──────────────────────────────────────────────────────


@respx.mock
async def test_graphql_countries_posts_query_and_slices_to_limit():
    route = respx.post(COUNTRIES_URL).respond(
        json={
            "data": {
                "continent": {
                    "countries": [{"name": "France"}, {"name": "Germany"}, {"name": "Spain"}]
                }
            }
        }
    )

    out = await base.execute_http(
        contract_body("graphql_countries_v0", "https://countries.trevorblades.com"),
        {"continent": "EU", "limit": 2},
    )

    assert out == {"countries": ["France", "Germany"]}
    assert route.called
    sent = json.loads(route.calls.last.request.content)
    assert sent["variables"] == {"c": "EU"}
    assert "continent" in sent["query"] and "$c" in sent["query"]


@respx.mock
async def test_graphql_countries_defaults_to_eu():
    route = respx.post(COUNTRIES_URL).respond(
        json={"data": {"continent": {"countries": [{"name": "France"}]}}}
    )

    out = await base.execute_http(
        contract_body("graphql_countries_v0", "https://countries.trevorblades.com"), {}
    )

    assert out["countries"] == ["France"]
    sent = json.loads(route.calls.last.request.content)
    assert sent["variables"] == {"c": "EU"}


@pytest.mark.parametrize("code", ["eur", "E1", "e", "EUR", "", "';--"])
async def test_graphql_countries_invalid_continent_raises_before_network(code: str):
    with respx.mock:
        with pytest.raises(ValueError):
            await base.execute_http(
                contract_body("graphql_countries_v0", "https://countries.trevorblades.com"),
                {"continent": code},
            )


# ── hn_firebase_v0 feeds ──────────────────────────────────────────────────────

HN_BODY = contract_body("hn_firebase_v0", "https://news.ycombinator.com")
FEED_URLS = {
    "top": "https://hacker-news.firebaseio.com/v0/topstories.json",
    "ask": "https://hacker-news.firebaseio.com/v0/askstories.json",
    "show": "https://hacker-news.firebaseio.com/v0/showstories.json",
}


@pytest.mark.parametrize("feed", ["top", "ask", "show"])
@respx.mock
async def test_hn_feed_selects_endpoint(feed: str):
    ids = [501, 502]
    respx.get(FEED_URLS[feed]).respond(json=ids)
    for i in ids:
        respx.get(item_url(i)).respond(
            json={"id": i, "title": f"{feed} story {i}", "url": f"https://example.com/{i}", "score": i}
        )

    out = await base.execute_http(HN_BODY, {"limit": 2, "feed": feed})

    stories = out["stories"]
    assert [s["rank"] for s in stories] == [1, 2]
    assert stories[0]["title"] == f"{feed} story 501"


async def test_hn_invalid_feed_raises_before_network():
    with respx.mock:
        with pytest.raises(ValueError):
            await base.execute_http(HN_BODY, {"limit": 2, "feed": "best"})


# ── SSRF allowlist (widened hosts + post_json) ────────────────────────────────


def test_allowlist_is_exactly_the_four_hosts():
    assert base.ALLOWED_HOSTS == EXPECTED_ALLOWED_HOSTS


@pytest.mark.parametrize("host", sorted(EXPECTED_ALLOWED_HOSTS))
def test_new_hosts_pass_assert_host_allowed(host: str):
    base.assert_host_allowed(f"https://{host}/anything")


async def test_get_json_blocks_evil_host():
    with pytest.raises(base.SSRFBlockedError):
        await base.get_json("https://evil.example.com/steal")


async def test_post_json_blocks_evil_host():
    with pytest.raises(base.SSRFBlockedError):
        await base.post_json("https://evil.example.com/steal", {"q": "x"})


async def test_post_json_blocks_non_https_scheme():
    with pytest.raises(base.SSRFBlockedError):
        await base.post_json("http://countries.trevorblades.com/", {"q": "x"})


@respx.mock
async def test_post_json_allows_allowlisted_host():
    respx.post(COUNTRIES_URL).respond(json={"ok": True})

    out = await base.post_json(COUNTRIES_URL, {"query": "{}"})

    assert out == {"ok": True}


def test_schema_to_model_handles_nullable_union_types():
    """Regression: ["string","null"] union types crashed _schema_to_model with
    TypeError unhashable list — killed the agent path for any nullable schema."""
    from app.services.h_client import _schema_to_model

    schema = {
        "type": "object",
        "required": ["full_name", "stars"],
        "properties": {
            "full_name": {"type": "string"},
            "stars": {"type": "integer"},
            "latest_release_tag": {"type": ["string", "null"]},
            "year": {"type": ["integer", "null"]},
        },
    }
    model = _schema_to_model(schema)
    assert model is not None
    obj = model(full_name="a/b", stars=1, latest_release_tag=None, year=None)
    assert obj.latest_release_tag is None
    obj2 = model(full_name="a/b", stars=1, latest_release_tag="v1.0.6", year=2024)
    assert obj2.year == 2024
