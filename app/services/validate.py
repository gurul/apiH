"""jsonschema validation + contract health checks (SPEC §Validation and health)."""

import copy
import logging

import jsonschema

logger = logging.getLogger(__name__)


class InputValidationError(ValueError): ...


class OutputValidationError(ValueError): ...


def validate_input(data: dict, schema: dict) -> dict:
    """Validate and return a copy with top-level property defaults applied."""
    result = copy.deepcopy(data)
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, prop in properties.items():
            if name not in result and isinstance(prop, dict) and "default" in prop:
                result[name] = prop["default"]
    try:
        jsonschema.validate(result, schema)
    except jsonschema.ValidationError as e:
        raise InputValidationError(f"input validation failed: {e.message}") from e
    return result


def validate_output(data: dict, schema: dict) -> None:
    try:
        jsonschema.validate(data, schema)
    except jsonschema.ValidationError as e:
        raise OutputValidationError(f"output validation failed: {e.message}") from e


def get_path(data: dict, dotted: str) -> object:
    """Resolve 'stories.0.title' style paths; numeric segments index lists."""
    current: object = data
    for seg in dotted.split("."):
        if isinstance(current, list):
            if not seg.lstrip("-").isdigit():
                raise KeyError(f"non-numeric segment {seg!r} for list in path {dotted!r}")
            current = current[int(seg)]
        elif isinstance(current, dict):
            current = current[seg]
        else:
            raise KeyError(f"cannot descend into {type(current).__name__} at {seg!r} in {dotted!r}")
    return current


def check_health(data: dict, health: dict | None, latency_ms: int, path: str) -> bool:
    if not health:
        return True

    min_array = health.get("min_array_length")
    if min_array:
        try:
            value = get_path(data, min_array["path"])
        except (KeyError, IndexError):
            return False
        if not isinstance(value, list) or len(value) < min_array.get("min", 1):
            return False

    for dotted in health.get("required_paths") or []:
        try:
            get_path(data, dotted)
        except (KeyError, IndexError):
            return False

    max_latency = health.get("max_latency_ms")
    if max_latency is not None and latency_ms > max_latency:
        # hard fail only for the expensive agent path; cheap http just warns
        if path == "agent":
            return False
        logger.warning(
            "http path latency %dms exceeded max_latency_ms budget %dms",
            latency_ms,
            max_latency,
        )

    return True
