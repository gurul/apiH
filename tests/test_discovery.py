"""Schema discovery: compile figures out the schemas from one exploration run,
persists them, and subsequent runs reuse the stored contract."""

from app.services import schema_infer


def test_infer_json_schema_merges_array_items() -> None:
    sample = {
        "listings": [
            {"rank": 1, "title": "A", "price": "$2,100", "url": "https://x/1"},
            {"rank": 2, "title": "B", "price": None, "url": "https://x/2"},
        ],
        "count": 2,
    }
    schema = schema_infer.infer_json_schema(sample)
    items = schema["properties"]["listings"]["items"]
    # union of properties, but required = only fields non-null in EVERY item
    assert set(items["properties"]) == {"rank", "title", "price", "url"}
    assert items["required"] == ["rank", "title", "url"]
    assert items["properties"]["rank"] == {"type": "integer"}
    assert schema["properties"]["count"] == {"type": "integer"}
    assert "listings" in schema["required"]


def test_derive_input_schema_from_goal_placeholders() -> None:
    schema = schema_infer.derive_input_schema(
        "Search {{site}} for {{query}} and return the top {{limit}} results"
    )
    props = schema["properties"]
    assert set(props) == {"query", "limit"}  # {{site}} is reserved, not an input
    assert props["limit"]["type"] == "integer" and props["limit"]["default"] == 5
    assert props["query"] == {"type": "string", "default": ""}


def test_discovery_compile_then_reuse(client, fast_agent) -> None:
    # Create with NO schemas — just site + goal with placeholders.
    r = client.post(
        "/v1/workflows",
        json={
            "slug": "craigslist-apartments",
            "title": "Craigslist apartments",
            "site": "https://sfbay.craigslist.org/search/apa",
            "goal": "Return the top {{limit}} apartment listings",
        },
    )
    assert r.status_code == 201
    assert r.json()["output_schema"] == {}

    # Compile triggers discovery (mock H here): schemas get filled in + contract v1.
    r = client.post(
        "/v1/workflows/craigslist-apartments/compile",
        json={"engine": "auto", "activate": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["job"]["status"] == "completed"
    contract = body["contract"]
    assert contract["version"] == 1 and contract["method"] == "agent"
    assert contract["body"]["output_schema"]["properties"]  # discovered, non-empty
    assert "sample_answer" in contract["body"]["compile_meta"]

    wf = client.get("/v1/workflows/craigslist-apartments").json()
    assert wf["input_schema"]["properties"]["limit"]["default"] == 5
    assert wf["output_schema"]["properties"]

    # Subsequent runs use the stored contract — no recompile, version stays 1.
    for _ in range(2):
        r = client.post(
            "/v1/workflows/craigslist-apartments/run", json={"input": {"limit": 3}}
        )
        assert r.status_code == 200
        assert r.json()["meta"]["path"] == "agent"
        assert r.json()["meta"]["contract_version"] == 1

    contracts = client.get("/v1/workflows/craigslist-apartments/contracts").json()
    assert len(contracts) == 1


def test_explicit_schemas_skip_discovery(client, db) -> None:
    from tests.conftest import INPUT_SCHEMA, OUTPUT_SCHEMA

    r = client.post(
        "/v1/workflows",
        json={
            "slug": "explicit-site",
            "title": "Explicit",
            "site": "https://example.com",
            "goal": "Return things",
            "input_schema": INPUT_SCHEMA,
            "output_schema": OUTPUT_SCHEMA,
        },
    )
    assert r.status_code == 201
    r = client.post(
        "/v1/workflows/explicit-site/compile", json={"engine": "auto", "activate": True}
    )
    assert r.status_code == 200
    body = r.json()["contract"]["body"]
    assert body["output_schema"] == OUTPUT_SCHEMA  # untouched by discovery
    assert "sample_answer" not in body["compile_meta"]
