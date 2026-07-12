"""H Computer-Use client. Mock by default; hai_agents imported lazily in live mode only."""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, create_model

from app.config import Settings, get_settings

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")
_LIMIT_HINT_RE = re.compile(r"\btop\s+(\d+)\b", re.IGNORECASE)

_JSON_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
}


@dataclass
class HResult:
    answer: dict
    session_id: str | None
    cost_usd: float | None
    engine: str  # "h" | "mock"


def render_prompt(template: str, variables: dict) -> str:
    """Safe {{var}} substitution only — no eval. Unknown vars are left as-is."""

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1)
        return str(variables[name]) if name in variables else m.group(0)

    return _VAR_RE.sub(_sub, template)


def _mock_stories(limit: int) -> dict:
    stories = []
    for i in range(1, limit + 1):
        item_url = f"https://news.ycombinator.com/item?id={40000000 + i}"
        stories.append(
            {
                "rank": i,
                "title": f"Mock HN story #{i}",
                "url": item_url,
                "points": 100 - i,
                "hn_url": item_url,
            }
        )
    return {"stories": stories}


def _schema_to_type(schema: dict, name: str) -> Any:
    t = schema.get("type")
    if t in _JSON_TYPES:
        return _JSON_TYPES[t]
    if t == "array":
        item = _schema_to_type(schema.get("items") or {}, f"{name}_item")
        return list[item] if item is not None else None
    if t == "object":
        return _schema_to_model(schema, name)
    return None


def _schema_to_model(schema: dict, name: str = "Answer") -> type[BaseModel] | None:
    """Dynamic Pydantic model for simple object schemas; None when not straightforward."""
    if schema.get("type") != "object" or not isinstance(schema.get("properties"), dict):
        return None
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for prop, sub in schema["properties"].items():
        typ = _schema_to_type(sub if isinstance(sub, dict) else {}, f"{name}_{prop}")
        if typ is None:
            return None
        fields[prop] = (typ, ...) if prop in required else (typ | None, None)
    return create_model(name, **fields)


def _run_live(prompt: str, output_schema: dict, settings: Settings) -> HResult:
    try:
        import hai_agents
    except ImportError as e:
        raise RuntimeError(
            "hai_agents is not installed — live H mode requires `pip install hai-agents`, "
            "or set API_H_MOCK_H=true for mock mode"
        ) from e

    # SDK requires a Pydantic model class (or None for the raw wire answer) — never
    # a raw schema dict. Discovery passes {"type": "object"} and lands on None.
    answer_schema = _schema_to_model(output_schema)
    try:
        client = hai_agents.Client(
            api_key=settings.hai_api_key,
            environment=getattr(
                hai_agents.HaiAgentsEnvironment, settings.hai_environment.upper()
            ),
        )
        result = client.run_session(
            agent=settings.hai_agent,
            messages=prompt,
            answer_schema=answer_schema,
            timeout_seconds=600,
        )
    except Exception as e:
        # Scrub the key in case the SDK echoes it in an error message.
        msg = str(e)
        if settings.hai_api_key:
            msg = msg.replace(settings.hai_api_key, "***")
        raise RuntimeError(f"H session failed: {msg}") from None

    # 'idle' is a success state too: the conversational session finished its run and
    # awaits further messages. Judge by outcome + answer, not by status alone.
    if result.status in ("failed", "timed_out", "interrupted") or result.outcome in (
        "infeasible",
        "blocked",
    ):
        raise RuntimeError(
            f"H session {result.id} ended {result.status}"
            f" (outcome={result.outcome}, error={result.error})"
        )
    answer = result.answer
    if isinstance(answer, BaseModel):
        answer = answer.model_dump()
    if isinstance(answer, str):
        # Without an answer_schema (discovery) the wire value is raw text — usually
        # JSON, sometimes fenced in ```json blocks.
        text = answer.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else text
        try:
            answer = json.loads(text)
        except ValueError:
            pass
    if isinstance(answer, list):
        answer = {"results": answer}
    if not isinstance(answer, dict):
        raise RuntimeError(
            f"H session {result.id} returned a non-object answer"
            f" (outcome={result.outcome})"
        )
    metrics = getattr(result.final_changes, "metrics", None) if result.final_changes else None
    cost_usd = getattr(metrics, "total_cost", None) if metrics is not None else None
    return HResult(answer=answer, session_id=result.id, cost_usd=cost_usd, engine="h")


async def run_h_session(prompt: str, output_schema: dict) -> HResult:
    settings = get_settings()
    if settings.h_mode == "mock":
        await asyncio.sleep(1.5)  # simulate agent latency
        m = _LIMIT_HINT_RE.search(prompt)
        limit = int(m.group(1)) if m else 5
        return HResult(answer=_mock_stories(limit), session_id=None, cost_usd=0.0, engine="mock")
    return await asyncio.to_thread(_run_live, prompt, output_schema, settings)


async def execute_agent(contract_body: dict, input: dict) -> HResult:
    agent = contract_body["agent"]
    prompt = render_prompt(
        agent["prompt_template"],
        {**input, "site": contract_body["site"], "goal": contract_body["goal"]},
    )
    return await run_h_session(prompt, contract_body["output_schema"])
