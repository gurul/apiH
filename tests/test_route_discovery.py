"""Captured-traffic ingestion, candidate derivation, and input matrix. Pure — no network."""

from app.services import route_discovery as rd

CAPTURE_SIMPLE = [
    {
        "method": "GET",
        "url": "https://api.example.com/v1/items?limit=5",
        "content_type": "application/json",
        "status": 200,
    },
    {
        "method": "GET",
        "url": "https://cdn.example.com/logo.png",
        "content_type": "image/png",
        "status": 200,
    },
    {
        "method": "POST",
        "url": "https://analytics.example.com/collect",
        "content_type": "application/json",
        "status": 204,
    },
]

CAPTURE_HAR = {
    "log": {
        "entries": [
            {
                "request": {
                    "method": "GET",
                    "url": "https://api.example.com/v1/items",
                    "queryString": [{"name": "limit", "value": "5"}],
                },
                "response": {"status": 200, "content": {"mimeType": "application/json"}},
            }
        ]
    }
}


# ── parse_captured_requests ───────────────────────────────────────────────────


def test_parse_simple_list():
    reqs = rd.parse_captured_requests(CAPTURE_SIMPLE)
    assert [r.host for r in reqs] == [
        "api.example.com",
        "cdn.example.com",
        "analytics.example.com",
    ]
    assert reqs[0].is_json and not reqs[1].is_json


def test_parse_har_extracts_query_and_json_flag():
    reqs = rd.parse_captured_requests(CAPTURE_HAR)
    assert len(reqs) == 1
    assert reqs[0].url == "https://api.example.com/v1/items"
    assert reqs[0].query == {"limit": "5"}
    assert reqs[0].is_json is True


def test_parse_accepts_json_string():
    import json

    reqs = rd.parse_captured_requests(json.dumps(CAPTURE_SIMPLE))
    assert len(reqs) == 3


def test_parse_tolerates_junk():
    assert rd.parse_captured_requests(None) == []
    assert rd.parse_captured_requests("not json") == []
    assert rd.parse_captured_requests([{"no_url": True}, 42]) == []


# ── derive_route_candidates ───────────────────────────────────────────────────


def test_agent_candidate_ranked_first_and_grounded():
    answer = {
        "candidates_json": (
            '[{"method":"GET","url":"https://api.example.com/v1/items",'
            '"query":{"limit":"{{limit}}"},"response_path":"items","output_key":"items"}]'
        ),
    }
    captured = rd.parse_captured_requests(CAPTURE_SIMPLE)
    cands = rd.derive_route_candidates(answer, captured)
    # agent candidate first; the JSON POST from capture also derived; the PNG is not.
    assert cands[0]["url"] == "https://api.example.com/v1/items"
    assert cands[0]["output_key"] == "items"
    hosts = {c["allowed_host"] for c in cands}
    assert hosts == {"api.example.com", "analytics.example.com"}


def test_candidate_host_absent_from_capture_is_dropped():
    answer = {"candidates_json": '[{"method":"GET","url":"https://other.example.org/data"}]'}
    captured = rd.parse_captured_requests(CAPTURE_SIMPLE)
    cands = rd.derive_route_candidates(answer, captured)
    assert all(c["allowed_host"] != "other.example.org" for c in cands)


def test_unsafe_candidate_url_rejected():
    answer = {"candidates_json": '[{"method":"GET","url":"http://api.example.com/x"}]'}
    captured = rd.parse_captured_requests(CAPTURE_SIMPLE)
    # http (not https) fails validate_generated_url; the http GET item survives via capture
    cands = rd.derive_route_candidates(answer, captured)
    assert all(c["url"].startswith("https://") for c in cands)


def test_legacy_single_route_fields_supported():
    answer = {
        "method": "GET",
        "url": "https://api.example.com/v1/items",
        "query_json": '{"limit":"{{limit}}"}',
        "response_path": "items",
    }
    cands = rd.derive_route_candidates(answer, [])
    assert cands[0]["query"] == {"limit": "{{limit}}"}


def test_no_capture_still_allows_agent_candidate():
    answer = {"candidates_json": '[{"method":"GET","url":"https://api.example.com/v1/items"}]'}
    cands = rd.derive_route_candidates(answer, [])
    assert len(cands) == 1


def test_duplicate_candidates_deduped():
    answer = {
        "candidates_json": (
            '[{"method":"GET","url":"https://api.example.com/a"},'
            '{"method":"GET","url":"https://api.example.com/a"}]'
        )
    }
    cands = rd.derive_route_candidates(answer, [])
    assert len(cands) == 1


# ── build_input_matrix ────────────────────────────────────────────────────────


def test_matrix_covers_integer_boundaries():
    schema = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 30}},
    }
    rows = rd.build_input_matrix(schema, {"limit": 5})
    limits = [r["limit"] for r in rows]
    assert limits[0] == 5  # defaults first
    assert 1 in limits and 30 in limits  # boundaries
    assert 3 <= len(rows) <= 5


def test_matrix_uses_enum_members():
    schema = {
        "type": "object",
        "properties": {"continent": {"type": "string", "enum": ["EU", "AS", "AF"]}},
    }
    rows = rd.build_input_matrix(schema, {"continent": "EU"})
    assert {r["continent"] for r in rows} == {"EU", "AS", "AF"}


def test_matrix_capped_and_single_row_when_no_variation():
    schema = {"type": "object", "properties": {"q": {"type": "string", "default": "x"}}}
    rows = rd.build_input_matrix(schema, {"q": "x"})
    assert rows == [{"q": "x"}]  # no fabricated strings
