"""Schema validation, health checks, and the fail-closed run path. Offline."""

import copy

import pytest
import respx

from app.services.validate import (
    InputValidationError,
    OutputValidationError,
    check_health,
    get_path,
    validate_input,
    validate_output,
)
from tests.conftest import (
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    create_hn_workflow,
    mock_firebase,
    story_items,
)


def test_validate_input_applies_defaults():
    assert validate_input({}, INPUT_SCHEMA) == {"limit": 5}
    assert validate_input({"limit": 2}, INPUT_SCHEMA)["limit"] == 2


def test_validate_input_rejects_wrong_type():
    with pytest.raises(InputValidationError):
        validate_input({"limit": "three"}, INPUT_SCHEMA)


def test_validate_output_missing_required_field():
    data = {"stories": [{"rank": 1, "title": "t", "url": "https://example.com"}]}  # no points
    with pytest.raises(OutputValidationError):
        validate_output(data, OUTPUT_SCHEMA)


def test_get_path_indexes_arrays():
    data = {"stories": [{"title": "t0"}, {"title": "t1"}]}
    assert get_path(data, "stories.1.title") == "t1"
    with pytest.raises((KeyError, IndexError)):
        get_path(data, "stories.5.title")


def test_check_health_latency_budget_per_path():
    data = {"stories": [{"title": "t", "url": "https://example.com"}]}
    health = {"max_latency_ms": 10, "max_latency_ms_agent": 500}
    assert check_health(data, health, 999, "agent") is False  # over agent budget
    assert check_health(data, health, 400, "agent") is True  # http budget ignored
    assert check_health(data, health, 999, "http") is True  # warn-log only for http
    # agent default budget is 10 min — minutes-long live runs must pass
    assert check_health(data, {"max_latency_ms": 10}, 240_000, "agent") is True
    assert check_health(data, {"max_latency_ms": 10}, 900_000, "agent") is False
    assert check_health(data, None, 999, "agent") is True


@respx.mock
def test_run_returns_502_and_persists_ok_zero_on_output_validation_failure(
    client, db, fast_agent
):
    # Contract requires a field no path can produce → http fails validation, and with
    # the agent disabled the run must fail closed.
    broken = copy.deepcopy(OUTPUT_SCHEMA)
    broken["properties"]["stories"]["items"]["required"].append("summary")
    wf = create_hn_workflow(db, slug="hn-broken-schema", output_schema=broken, agent_enabled=False)
    ids = [301, 302]
    mock_firebase(respx, ids, story_items(ids))

    resp = client.post(f"/v1/workflows/{wf.slug}/run", json={"input": {"limit": 2}})

    assert resp.status_code == 502
    payload = resp.json()
    assert payload["ok"] is False
    assert payload["errors"]
    assert payload["run_id"]

    from app import models

    db.expire_all()
    run = db.get(models.Run, payload["run_id"])
    assert run is not None
    assert run.ok == 0
    assert run.error
