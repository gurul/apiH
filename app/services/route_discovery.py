"""Turn captured browser network traffic into replayable HTTP route candidates.

The H exploration session browses the workflow site and records the network
requests it actually observed — the evidence. This module ingests that evidence
(HAR-shaped or a simple request list), filters it to replayable public JSON
requests, and ranks candidate route plans. Verification (replay across a small
input matrix) happens in the compiler; this module is pure, deterministic, and
fully offline-testable.
"""

import json
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from app.services.http_executors.generated import validate_generated_url

_JSON_HINTS = ("json", "graphql")


@dataclass
class CapturedRequest:
    """One network request observed during the exploration session."""

    method: str
    url: str
    host: str
    query: dict
    body: dict
    content_type: str
    status: int | None
    is_json: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _loads_obj(raw: Any) -> dict:
    """Parse a JSON object (string or already a dict) → dict; {} on anything else."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _coerce_entries(raw: Any) -> list:
    """Accept a JSON string, a HAR log, an entries list, or a single entry."""
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if isinstance(raw, dict):
        log = raw.get("log")
        if isinstance(log, dict) and isinstance(log.get("entries"), list):
            return log["entries"]
        if isinstance(raw.get("entries"), list):
            return raw["entries"]
        return [raw]
    if isinstance(raw, list):
        return raw
    return []


def _har_query(req: dict) -> dict:
    pairs = req.get("queryString")
    if isinstance(pairs, list):
        return {p["name"]: p.get("value", "") for p in pairs if isinstance(p, dict) and "name" in p}
    return _loads_obj(req.get("query"))


def _har_body(req: dict) -> dict:
    post = req.get("postData")
    if isinstance(post, dict) and post.get("text"):
        return _loads_obj(post["text"])
    return _loads_obj(req.get("body"))


def _content_type(req: dict, resp: dict) -> str:
    content = resp.get("content")
    if isinstance(content, dict) and content.get("mimeType"):
        return str(content["mimeType"])
    return str(resp.get("content_type") or req.get("content_type") or "")


def _normalize(entry: Any) -> CapturedRequest | None:
    if not isinstance(entry, dict):
        return None
    req = entry.get("request") if isinstance(entry.get("request"), dict) else entry
    resp = entry.get("response") if isinstance(entry.get("response"), dict) else {}
    url = str(req.get("url") or "")
    if not url:
        return None
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return None
    content_type = _content_type(req, resp)
    status = resp.get("status") if isinstance(resp.get("status"), int) else entry.get("status")
    declared = entry.get("is_json")
    is_json = bool(declared) if isinstance(declared, bool) else any(
        h in content_type.lower() for h in _JSON_HINTS
    )
    return CapturedRequest(
        method=str(req.get("method") or "GET").upper(),
        url=url,
        host=host,
        query=_har_query(req),
        body=_har_body(req),
        content_type=content_type,
        status=status if isinstance(status, int) else None,
        is_json=is_json,
    )


def parse_captured_requests(raw: Any) -> list[CapturedRequest]:
    """Ingest captured traffic (HAR-shaped or a simple request list) → records."""
    return [rec for entry in _coerce_entries(raw) if (rec := _normalize(entry)) is not None]


def _safe_candidate(plan: dict) -> dict | None:
    """Normalize + SSRF/URL-safety check one candidate plan; None if unusable."""
    method = str(plan.get("method") or "GET").upper()
    if method not in {"GET", "POST"}:
        return None
    url = str(plan.get("url") or "")
    try:
        allowed_host = validate_generated_url(url)
    except ValueError:
        return None
    query = plan.get("query") if isinstance(plan.get("query"), dict) else _loads_obj(plan.get("query_json"))
    body = plan.get("body") if isinstance(plan.get("body"), dict) else _loads_obj(plan.get("body_json"))
    return {
        "method": method,
        "url": url,
        "allowed_host": allowed_host,
        "query": query,
        "body": body,
        "response_path": str(plan.get("response_path") or ""),
        "output_key": str(plan.get("output_key") or ""),
    }


def _candidate_key(cand: dict) -> tuple:
    return (
        cand["method"],
        cand["url"],
        json.dumps(cand["query"], sort_keys=True),
        json.dumps(cand["body"], sort_keys=True),
    )


def _proposed_plans(answer: dict) -> list[dict]:
    """Agent-proposed candidates: a candidates_json list first, then legacy single-route fields."""
    plans: list[dict] = []
    raw = answer.get("candidates_json")
    if raw:
        try:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError:
            parsed = None
        if isinstance(parsed, list):
            plans.extend(p for p in parsed if isinstance(p, dict))
        elif isinstance(parsed, dict):
            plans.append(parsed)
    if answer.get("url"):
        plans.append(
            {
                "method": answer.get("method"),
                "url": answer.get("url"),
                "query_json": answer.get("query_json"),
                "body_json": answer.get("body_json"),
                "response_path": answer.get("response_path"),
                "output_key": answer.get("output_key"),
            }
        )
    return plans


def derive_route_candidates(answer: dict, captured: list[CapturedRequest]) -> list[dict]:
    """Ordered, safety-checked candidate route plans grounded in captured evidence.

    Agent-proposed candidates come first (highest confidence), then any additional
    replayable JSON GET/POST observed in the capture. Every candidate must pass the
    generated-route URL safety checks; when the capture is non-empty, a candidate's
    host must also appear in it — a route the agent never actually exercised is not
    evidence-backed and is dropped.
    """
    captured_hosts = {c.host for c in captured if c.host}
    ordered: list[dict] = []
    seen: set[tuple] = set()

    def add(cand: dict | None) -> None:
        if cand is None:
            return
        if captured_hosts and cand["allowed_host"] not in captured_hosts:
            return
        key = _candidate_key(cand)
        if key in seen:
            return
        seen.add(key)
        ordered.append(cand)

    for proposed in _proposed_plans(answer):
        add(_safe_candidate(proposed))

    # Extra candidates derived straight from captured JSON GET/POST requests, reusing
    # the agent's response_path/output_key selection (the shaping it worked out).
    fallback_path = str(answer.get("response_path") or "")
    fallback_key = str(answer.get("output_key") or "")
    for c in captured:
        if not c.is_json or c.method not in {"GET", "POST"}:
            continue
        add(
            _safe_candidate(
                {
                    "method": c.method,
                    "url": c.url,
                    "query": c.query,
                    "body": c.body,
                    "response_path": fallback_path,
                    "output_key": fallback_key,
                }
            )
        )
    return ordered


def build_input_matrix(
    input_schema: dict, defaults: dict, max_rows: int = 5
) -> list[dict]:
    """A small matrix of varied inputs for replay verification.

    Row 0 is the defaults. Additional rows vary one property at a time using
    schema-derived boundary values (integer min/max/midpoint, enum members) so
    replay exercises the route beyond a single input. Capped at ``max_rows``; only
    values the schema actually affords are produced (no fabricated strings).
    """
    base = dict(defaults)
    rows: list[dict] = [base]
    for name, prop in (input_schema.get("properties") or {}).items():
        if not isinstance(prop, dict):
            continue
        variants: list[Any] = []
        if prop.get("type") == "integer":
            lo, hi = prop.get("minimum"), prop.get("maximum")
            if isinstance(lo, int):
                variants.append(lo)
            if isinstance(hi, int):
                variants.append(hi)
            if isinstance(lo, int) and isinstance(hi, int) and hi - lo >= 2:
                variants.append((lo + hi) // 2)
        elif isinstance(prop.get("enum"), list):
            variants.extend(prop["enum"])
        for value in variants:
            row = {**base, name: value}
            if row not in rows:
                rows.append(row)
    return rows[:max_rows]
