"""Schema discovery: infer an output JSON Schema from one sample answer, and derive
the input schema from {{placeholder}} variables in the workflow goal."""

import re
from typing import Any

PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# Reserved names always available to prompts — never caller inputs.
_RESERVED = {"site", "goal"}

_KNOWN_INPUTS: dict[str, dict[str, Any]] = {
    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 30},
}


def derive_input_schema(goal: str) -> dict[str, Any]:
    """Each {{var}} in the goal becomes an input property; 'limit' gets integer
    semantics, everything else is a free string defaulting to empty."""
    props: dict[str, Any] = {}
    for name in PLACEHOLDER_RE.findall(goal):
        if name in _RESERVED or name in props:
            continue
        props[name] = dict(_KNOWN_INPUTS.get(name, {"type": "string", "default": ""}))
    return {"type": "object", "properties": props}


def input_defaults(input_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        name: prop.get("default", "")
        for name, prop in (input_schema.get("properties") or {}).items()
    }


def infer_json_schema(sample: Any) -> dict[str, Any]:
    if isinstance(sample, bool):
        return {"type": "boolean"}
    if isinstance(sample, int):
        return {"type": "integer"}
    if isinstance(sample, float):
        return {"type": "number"}
    if isinstance(sample, str):
        return {"type": "string"}
    if sample is None:
        return {"type": ["string", "null"]}
    if isinstance(sample, list):
        return {"type": "array", "items": _infer_items(sample)}
    if isinstance(sample, dict):
        return {
            "type": "object",
            "required": sorted(k for k, v in sample.items() if v is not None),
            "properties": {k: infer_json_schema(v) for k, v in sample.items()},
        }
    return {}


def _infer_items(items: list[Any]) -> dict[str, Any]:
    """Merge object items: properties = union, required = keys non-null in EVERY item
    (a field missing from one listing must not fail validation for all)."""
    if not items:
        return {}
    if not all(isinstance(x, dict) for x in items):
        return infer_json_schema(items[0])
    props: dict[str, Any] = {}
    required: set[str] | None = None
    for x in items:
        for k, v in x.items():
            props.setdefault(k, infer_json_schema(v))
        present = {k for k, v in x.items() if v is not None}
        required = present if required is None else required & present
    return {"type": "object", "required": sorted(required or set()), "properties": props}
