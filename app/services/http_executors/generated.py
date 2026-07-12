"""Restricted executor for HTTP route plans produced by an H exploration session.

Generated plans are data, not arbitrary Python.  The executor supports one public
JSON GET/POST, template substitution from validated workflow inputs, an optional
response path, and optional wrapping under an output key.
"""

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

from app.services.http_executors.base import get_client, register_mapper

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


def _render(value: Any, inputs: dict) -> Any:
    if isinstance(value, str):
        match = _VAR_RE.fullmatch(value)
        if match and match.group(1) in inputs:
            return inputs[match.group(1)]
        return _VAR_RE.sub(lambda m: str(inputs.get(m.group(1), m.group(0))), value)
    if isinstance(value, list):
        return [_render(item, inputs) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, inputs) for key, item in value.items()}
    return value


def validate_generated_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not host or parsed.username or parsed.password:
        raise ValueError("generated route must use an unauthenticated HTTPS URL")
    if host == "localhost" or host.endswith(".local"):
        raise ValueError("generated route cannot target a local host")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("generated route cannot target a private or reserved address")
    return host


def _select_path(payload: Any, path: str) -> Any:
    current = payload
    for part in filter(None, path.split(".")):
        if isinstance(current, list):
            current = current[int(part)]
        elif isinstance(current, dict):
            current = current[part]
        else:
            raise ValueError(f"cannot select {path!r} from generated route response")
    return current


@register_mapper("generated_http_v1")
async def execute_generated(contract_body: dict, inputs: dict) -> dict:
    config = contract_body["http"]
    plan = config.get("plan") or {}
    method = str(plan.get("method", "GET")).upper()
    if method not in {"GET", "POST"}:
        raise ValueError(f"generated route method {method!r} is not supported")

    url = _render(str(plan["url"]), inputs)
    host = validate_generated_url(url)
    if host != config.get("allowed_host"):
        raise ValueError("generated route host differs from its compiled allowlist")

    query = _render(plan.get("query") or {}, inputs)
    body = _render(plan.get("body") or {}, inputs)
    client = get_client()
    if method == "GET":
        response = await client.get(url, params=query)
    else:
        response = await client.post(url, params=query, json=body)
    response.raise_for_status()
    payload = response.json()

    selected = _select_path(payload, str(plan.get("response_path") or ""))
    output_key = str(plan.get("output_key") or "")
    if output_key:
        return {output_key: selected}
    if not isinstance(selected, dict):
        raise ValueError("generated route must select an object or declare output_key")
    return selected
