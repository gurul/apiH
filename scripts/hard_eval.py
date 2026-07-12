"""Hard eval battery — 19 tasks across JS profiles, driven ONLY via the REST API.

Run from repo root (server must already be up; this script never starts one):

  uv run python scripts/hard_eval.py --base-url http://127.0.0.1:8000 --tasks all

Waves: W0 health, setup (create workflows + compile; discovery compiles gated by the
H semaphore), W1 HTTP sampling, W2/W3 agent runs (K = --h-concurrency), W4 concurrency
burst (20x hn-top-baseline HTTP), extras only if run+cost budget remains after 1-15.
Output: JSONL (one line per compile/run) + markdown report (Tables 1-4, Gates G1-G9,
narrative). Idempotent: 409 on create is fine; --skip-compile-if-active reuses
active contracts.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

JS_HEAVY_PROFILES = {"csr", "spa", "scroll", "consent", "dynamic", "softbot"}
MULTI_AGENT_GUIDANCE_URL = "https://hub.hcompany.ai/computer-use-agents/multi-agent"

DEFAULT_RUN_TIMEOUT_S = 660.0
SOFTWALL_TIMEOUT_S = 120.0
HTTP_SAMPLE_TIMEOUT_S = 60.0
COMPILE_TIMEOUT_S = 660.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _limit_schema(default: int, maximum: int = 30) -> dict[str, Any]:
    return {"type": "integer", "default": default, "minimum": 1, "maximum": maximum}


HN_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"limit": _limit_schema(5)},
}

HN_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["stories"],
    "properties": {
        "stories": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rank", "title", "url", "points"],
                "properties": {
                    "rank": {"type": "integer"},
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "points": {"type": "integer"},
                    "hn_url": {"type": "string"},
                },
            },
        }
    },
}

_EMPTY_INPUT: dict[str, Any] = {"type": "object", "properties": {}}


TASKS: list[dict[str, Any]] = [
    {
        "task_id": "hn-top-baseline",
        "slug": "hn-top-stories",
        "site": "https://news.ycombinator.com",
        "goal": "Return the top {{limit}} front-page stories",
        "js_profile": "api",
        "expected_path": "http",
        "difficulty": 1,
        "input_schema": HN_INPUT_SCHEMA,
        "output_schema": HN_OUTPUT_SCHEMA,
        "compile_engine": "mock",
        "run_input": {"limit": 10},
        "agent": False,
        "http_samples": None,  # None → --http-samples
        "extra": False,
    },
    {
        "task_id": "hn-ask-show",
        "slug": "hn-ask-show",
        "site": "https://news.ycombinator.com",
        "goal": "Return the top {{limit}} Show HN stories from the Show feed",
        "js_profile": "api",
        "expected_path": "http",
        "difficulty": 2,
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": _limit_schema(5),
                "feed": {"type": "string", "default": "show"},
            },
        },
        "output_schema": HN_OUTPUT_SCHEMA,
        "compile_engine": "mock",
        "run_input": {"limit": 5, "feed": "show"},
        "agent": False,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "wikipedia-toc",
        "slug": "wikipedia-toc",
        "site": "https://en.wikipedia.org/wiki/Web_scraping",
        "goal": (
            "Read the article. Return the lead paragraph text and the section outline "
            "(H2/H3 headings in order with level 2 or 3)"
        ),
        "js_profile": "static",
        "expected_path": "agent",
        "difficulty": 2,
        "input_schema": _EMPTY_INPUT,
        "output_schema": {
            "type": "object",
            "required": ["lead", "sections"],
            "properties": {
                "lead": {"type": "string"},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "level"],
                        "properties": {
                            "title": {"type": "string"},
                            "level": {"type": "integer"},
                        },
                    },
                },
            },
        },
        "compile_engine": "mock",
        "run_input": {},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "github-repo-meta",
        "slug": "github-repo-meta",
        "site": "https://github.com/hcompai/hai-agents-python",
        "goal": (
            "Report full_name, stars, forks, open_issues, default_branch and "
            "latest_release_tag (null if no release). Counts as integers "
            "(expand K/1.2k notation)."
        ),
        "js_profile": "spa",
        "expected_path": "agent",
        "difficulty": 3,
        "input_schema": _EMPTY_INPUT,
        "output_schema": {
            "type": "object",
            "required": ["full_name", "stars", "forks", "open_issues", "default_branch"],
            "properties": {
                "full_name": {"type": "string"},
                "stars": {"type": "integer"},
                "forks": {"type": "integer"},
                "open_issues": {"type": "integer"},
                "default_branch": {"type": "string"},
                "latest_release_tag": {"type": ["string", "null"]},
            },
        },
        "compile_engine": "mock",
        "run_input": {},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "craigslist-sf-bikes",
        "slug": "craigslist-sf-bikes",
        "site": "https://sfbay.craigslist.org/search/bia?max_price=500",
        "goal": (
            "Return {{limit}} bike listings under $500: title, price, url, location "
            "(location may be empty string)"
        ),
        "js_profile": "softbot",
        "expected_path": "agent",
        "difficulty": 4,
        "input_schema": {"type": "object", "properties": {"limit": _limit_schema(5)}},
        "output_schema": {
            "type": "object",
            "required": ["listings"],
            "properties": {
                "listings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "price", "url"],
                        "properties": {
                            "title": {"type": "string"},
                            "price": {"type": "string"},
                            "url": {"type": "string"},
                            "location": {"type": "string"},
                        },
                    },
                }
            },
        },
        "compile_engine": "mock",
        "run_input": {"limit": 5},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "hn-algolia-ui",
        "slug": "hn-algolia-ui",
        "site": "https://hn.algolia.com",
        "goal": (
            "Use the search box to search for 'Show HN'. Return the first {{limit}} "
            "results: title, url (null if none), points (integer), created_at"
        ),
        "js_profile": "csr",
        "expected_path": "agent",
        "difficulty": 3,
        "input_schema": {"type": "object", "properties": {"limit": _limit_schema(5)}},
        "output_schema": {
            "type": "object",
            "required": ["hits"],
            "properties": {
                "hits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "points", "created_at"],
                        "properties": {
                            "title": {"type": "string"},
                            "url": {"type": ["string", "null"]},
                            "points": {"type": "integer"},
                            "created_at": {"type": "string"},
                        },
                    },
                }
            },
        },
        "compile_engine": "mock",
        "run_input": {"limit": 5},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "quotes-js-rendered",
        "slug": "quotes-js-rendered",
        "site": "https://quotes.toscrape.com/js",
        "goal": (
            "Return the first {{limit}} quotes visible after the page renders: text, "
            "author, tags (list of strings)"
        ),
        "js_profile": "csr",
        "expected_path": "agent",
        "difficulty": 3,
        "input_schema": None,  # DISCOVERY — the JS litmus, compile first
        "output_schema": None,
        "compile_engine": "auto",
        "run_input": {"limit": 5},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "quotes-scroll",
        "slug": "quotes-scroll",
        "site": "https://quotes.toscrape.com/scroll",
        "goal": (
            "Scroll down until at least {{limit}} quotes have loaded, then return "
            "them: text, author, tags. No duplicates."
        ),
        "js_profile": "scroll",
        "expected_path": "agent",
        "difficulty": 4,
        "input_schema": None,  # DISCOVERY — litmus
        "output_schema": None,
        "compile_engine": "auto",
        "run_input": {"limit": 10},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "weather-wttr",
        "slug": "weather-wttr",
        "site": "https://wttr.in",
        "goal": "Return current weather for {{city}}: temp_C, humidity, weather_desc",
        "js_profile": "api",
        "expected_path": "http",
        "difficulty": 1,
        "input_schema": {
            "type": "object",
            "properties": {"city": {"type": "string", "default": "London"}},
        },
        "output_schema": {
            "type": "object",
            "required": ["temp_C", "humidity", "weather_desc"],
            "properties": {
                "temp_C": {"type": "string"},
                "humidity": {"type": "string"},
                "weather_desc": {"type": "string"},
            },
        },
        "compile_engine": "mock",
        "run_input": {"city": "London"},
        "agent": False,
        "http_samples": 10,
        "extra": False,
    },
    {
        "task_id": "openlibrary-search",
        "slug": "openlibrary-search",
        "site": "https://openlibrary.org",
        "goal": "Search for {{q}} and return {{limit}} works: title, authors, year, key",
        "js_profile": "api",
        "expected_path": "http",
        "difficulty": 2,
        "input_schema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "limit": _limit_schema(5, maximum=20),
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["works"],
            "properties": {
                "works": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "authors", "key"],
                        "properties": {
                            "title": {"type": "string"},
                            "authors": {"type": "array", "items": {"type": "string"}},
                            "year": {"type": ["integer", "null"]},
                            "key": {"type": "string"},
                        },
                    },
                }
            },
        },
        "compile_engine": "mock",
        "run_input": {"q": "foundation asimov", "limit": 5},
        "agent": False,
        "http_samples": 5,
        "extra": False,
    },
    {
        "task_id": "books-toscrape",
        "slug": "books-toscrape",
        "site": "https://books.toscrape.com",
        "goal": (
            "From catalogue page 1 return {{limit}} books: title, price, rating "
            "(one|two|three|four|five as written), in_stock (boolean)"
        ),
        "js_profile": "static",
        "expected_path": "agent",
        "difficulty": 2,
        "input_schema": {"type": "object", "properties": {"limit": _limit_schema(5)}},
        "output_schema": {
            "type": "object",
            "required": ["books"],
            "properties": {
                "books": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["title", "price", "rating", "in_stock"],
                        "properties": {
                            "title": {"type": "string"},
                            "price": {"type": "string"},
                            "rating": {
                                "type": "string",
                                "enum": ["one", "two", "three", "four", "five"],
                            },
                            "in_stock": {"type": "boolean"},
                        },
                    },
                }
            },
        },
        "compile_engine": "mock",
        "run_input": {"limit": 5},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "demoqa-dynamic",
        "slug": "demoqa-dynamic",
        "site": "https://the-internet.herokuapp.com/dynamic_loading/2",
        "goal": (
            "Click Start, wait for the loading to finish, and return status ('ok') "
            "and the text that appears"
        ),
        "js_profile": "dynamic",
        "expected_path": "agent",
        "difficulty": 4,
        "input_schema": _EMPTY_INPUT,
        "output_schema": {
            "type": "object",
            "required": ["status", "text"],
            "properties": {"status": {"type": "string"}, "text": {"type": "string"}},
        },
        "compile_engine": "mock",
        "run_input": {},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "spa-nav",
        "slug": "spa-nav",
        "site": "https://demoqa.com/books",
        "goal": (
            "In the Book Store application open the first book in the list and "
            "return its title, author and publisher"
        ),
        "js_profile": "spa",
        "expected_path": "agent",
        "difficulty": 4,
        "input_schema": _EMPTY_INPUT,
        "output_schema": {
            "type": "object",
            "required": ["title", "author", "publisher"],
            "properties": {
                "title": {"type": "string"},
                "author": {"type": "string"},
                "publisher": {"type": "string"},
            },
        },
        "compile_engine": "mock",
        "run_input": {},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "cookie-consent-content",
        "slug": "cookie-consent-content",
        "site": "https://www.theguardian.com/europe",
        "goal": (
            "If a cookie consent dialog appears, reject or dismiss non-essential "
            "cookies. Then return the main headline and 3 other visible headlines"
        ),
        "js_profile": "consent",
        "expected_path": "agent",
        "difficulty": 4,
        "input_schema": _EMPTY_INPUT,
        "output_schema": {
            "type": "object",
            "required": ["headline", "others"],
            "properties": {
                "headline": {"type": "string"},
                "others": {"type": "array", "items": {"type": "string"}},
            },
        },
        "compile_engine": "mock",
        "run_input": {},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "github-issues-spa",
        "slug": "github-issues-spa",
        "site": "https://github.com/hcompai/hai-agents-python/issues",
        "goal": (
            "Return {{limit}} open issues: number (integer), title, author, labels "
            "(list of strings, may be empty)"
        ),
        "js_profile": "spa",
        "expected_path": "agent",
        "difficulty": 4,
        "input_schema": {"type": "object", "properties": {"limit": _limit_schema(5)}},
        "output_schema": {
            "type": "object",
            "required": ["issues"],
            "properties": {
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["number", "title", "author"],
                        "properties": {
                            "number": {"type": "integer"},
                            "title": {"type": "string"},
                            "author": {"type": "string"},
                            "labels": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                }
            },
        },
        "compile_engine": "mock",
        "run_input": {"limit": 5},
        "agent": True,
        "http_samples": None,
        "extra": False,
    },
    {
        "task_id": "hn-item-thread",
        "slug": "hn-item-thread",
        "site": "https://news.ycombinator.com/item",
        "goal": (
            "Open the current top story's comment page and return story_title plus "
            "the top {{limit}} comments: author and first sentence of text"
        ),
        "js_profile": "static",
        "expected_path": "agent",
        "difficulty": 3,
        "input_schema": {"type": "object", "properties": {"limit": _limit_schema(3)}},
        "output_schema": {
            "type": "object",
            "required": ["story_title", "comments"],
            "properties": {
                "story_title": {"type": "string"},
                "comments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["author", "text"],
                        "properties": {
                            "author": {"type": "string"},
                            "text": {"type": "string"},
                        },
                    },
                },
            },
        },
        "compile_engine": "mock",
        "run_input": {"limit": 3},
        "agent": True,
        "http_samples": None,
        "extra": True,
    },
    {
        "task_id": "multi-step-js-chain",
        "slug": "multi-step-js-chain",
        "site": "https://quotes.toscrape.com/js",
        "goal": (
            "Read the first quote's author on the JS-rendered page, then search "
            "Wikipedia for that author and return the author name and the first "
            "sentence of their Wikipedia article."
        ),
        "js_profile": "csr",
        "expected_path": "agent",
        "difficulty": 5,
        "input_schema": _EMPTY_INPUT,
        "output_schema": {
            "type": "object",
            "required": ["author", "wiki_lead"],
            "properties": {
                "author": {"type": "string"},
                "wiki_lead": {"type": "string"},
            },
        },
        "compile_engine": "mock",
        "run_input": {},
        "agent": True,
        "http_samples": None,
        "extra": True,
    },
    {
        "task_id": "softwall-probe",
        "slug": "softwall-probe",
        "site": "https://www.ticketmaster.com",
        "goal": (
            "Open the homepage. If a bot check, challenge or access-denied page "
            "appears, return status 'blocked' with detail. If it loads, return "
            "status 'ok' and the page title."
        ),
        "js_profile": "softbot",
        "expected_path": "agent",
        "difficulty": 5,
        "input_schema": _EMPTY_INPUT,
        "output_schema": {
            "type": "object",
            "required": ["status", "detail"],
            "properties": {
                "status": {"type": "string"},
                "title": {"type": ["string", "null"]},
                "detail": {"type": "string"},
            },
        },
        "compile_engine": "mock",
        "run_input": {},
        "agent": True,
        "http_samples": None,
        "extra": True,
        "timeout_s": SOFTWALL_TIMEOUT_S,
    },
    {
        "task_id": "graphql-countries",
        "slug": "graphql-countries",
        "site": "https://countries.trevorblades.com",
        "goal": "Return {{limit}} country names on continent {{continent}}",
        "js_profile": "graphql",
        "expected_path": "http",
        "difficulty": 1,
        "input_schema": {
            "type": "object",
            "properties": {
                "continent": {"type": "string", "default": "EU"},
                "limit": _limit_schema(5, maximum=20),
            },
        },
        "output_schema": {
            "type": "object",
            "required": ["countries"],
            "properties": {
                "countries": {"type": "array", "items": {"type": "string"}},
            },
        },
        "compile_engine": "mock",
        "run_input": {"continent": "EU", "limit": 5},
        "agent": False,
        "http_samples": 5,
        "extra": False,
    },
]


class Recorder:
    """Collects JSONL records and enforces the agent-op + cost budget."""

    def __init__(self, out_path: Path, max_agent_runs: int, max_cost_usd: float) -> None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = out_path.open("w", encoding="utf-8")
        self.records: list[dict[str, Any]] = []
        self.record_waves: list[str] = []
        self.max_agent_runs = max_agent_runs
        self.max_cost_usd = max_cost_usd
        self.agent_ops = 0
        self.skipped_ops: list[str] = []

    @property
    def total_cost_usd(self) -> float:
        return sum(r["cost_usd"] or 0.0 for r in self.records)

    def budget_ok(self) -> bool:
        return (
            self.agent_ops < self.max_agent_runs
            and self.total_cost_usd < self.max_cost_usd
        )

    def reserve_agent_op(self, label: str) -> bool:
        if not self.budget_ok():
            self.skipped_ops.append(label)
            return False
        self.agent_ops += 1
        return True

    def record(self, wave: str, rec: dict[str, Any]) -> None:
        self.records.append(rec)
        self.record_waves.append(wave)
        self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._fh.flush()

    def by_wave(self, wave: str) -> list[dict[str, Any]]:
        return [r for r, w in zip(self.records, self.record_waves) if w == wave]

    def close(self) -> None:
        self._fh.close()


def infer_error_class(
    task: dict[str, Any],
    *,
    ok: bool,
    data: dict[str, Any] | None,
    http_status: int | None,
    error: str | None,
    timed_out: bool,
) -> str:
    text = (error or "").lower()
    if ok:
        if (
            task["task_id"] == "softwall-probe"
            and isinstance(data, dict)
            and data.get("status") == "blocked"
        ):
            return "blocked"
        return "none"
    if timed_out or "timed_out" in text or "timeout" in text:
        return "timeout"
    if any(k in text for k in ("blocked", "captcha", "denied", "forbidden")):
        return "blocked"
    empty_signal = "min_array" in text or "empty" in text or (
        "health_failed" in text and data is None
    )
    if empty_signal:
        if task["js_profile"] in ("csr", "scroll", "dynamic"):
            return "hydration"
        return "empty"
    if http_status == 502 and any(
        k in text for k in ("schema", "output", "validation", "health_failed")
    ):
        return "schema"
    return "other"


def base_record(task: dict[str, Any], kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "task_id": task["task_id"],
        "slug": task["slug"],
        "site": task["site"],
        "js_profile": task["js_profile"],
        "expected_path": task["expected_path"],
        "difficulty": task["difficulty"],
        "ok": False,
        "path": None,
        "latency_ms": 0,
        "cost_usd": None,
        "h_session_id": None,
        "contract_version": None,
        "http_status": None,
        "error_class": "other",
        "error": None,
        "ts": now_iso(),
        "note": None,
    }


def _json_body(resp: httpx.Response) -> dict[str, Any]:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {"body": body}
    except Exception:
        return {}


async def do_run(
    client: httpx.AsyncClient,
    task: dict[str, Any],
    wave: str,
    rec: Recorder,
    *,
    run_input: dict[str, Any],
    force_path: str | None = None,
    timeout: float = DEFAULT_RUN_TIMEOUT_S,
    label: str = "",
) -> dict[str, Any]:
    record = base_record(task, "run")
    payload: dict[str, Any] = {"input": run_input}
    if force_path is not None:
        payload["force_path"] = force_path
    data: dict[str, Any] | None = None
    timed_out = False
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"/v1/workflows/{task['slug']}/run", json=payload, timeout=timeout
        )
        record["http_status"] = resp.status_code
        body = _json_body(resp)
        if resp.status_code == 200 and body.get("ok"):
            meta = body.get("meta") or {}
            data = body.get("data")
            record["ok"] = True
            record["path"] = meta.get("path")
            record["latency_ms"] = int(meta.get("latency_ms") or 0)
            record["cost_usd"] = meta.get("cost_usd")
            record["h_session_id"] = meta.get("h_session_id")
            record["contract_version"] = meta.get("contract_version")
        else:
            errors = body.get("errors") or body.get("detail") or body
            record["error"] = json.dumps(errors, ensure_ascii=False)[:2000]
    except httpx.TimeoutException:
        timed_out = True
        record["error"] = f"client timeout after {timeout:.0f}s"
    except Exception as e:
        record["error"] = f"{type(e).__name__}: {e}"
    if not record["ok"]:
        record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    if task["expected_path"] == "http" and record["path"] == "agent":
        record["note"] = "TRAP"
    record["error_class"] = infer_error_class(
        task,
        ok=bool(record["ok"]),
        data=data,
        http_status=record["http_status"],
        error=record["error"],
        timed_out=timed_out,
    )
    rec.record(wave, record)
    result = "ok" if record["ok"] else f"FAIL ({record['error_class']})"
    trap = " TRAP" if record["note"] == "TRAP" else ""
    print(
        f"[{wave}] {task['task_id']}{f' {label}' if label else ''}: {result} "
        f"path={record['path']} {record['latency_ms']}ms{trap}",
        flush=True,
    )
    return record


async def setup_task(
    client: httpx.AsyncClient,
    task: dict[str, Any],
    rec: Recorder,
    sem: asyncio.Semaphore,
    args: argparse.Namespace,
    h_mode: str,
) -> dict[str, Any] | None:
    """Create workflow if missing (409 → fine), compile unless an active contract is
    reused. Returns {'method': ..., 'version': ...} or None on failure."""
    slug = task["slug"]
    discovery = task["input_schema"] is None and task["output_schema"] is None

    wf_resp = await client.get(f"/v1/workflows/{slug}")
    if wf_resp.status_code == 404:
        payload: dict[str, Any] = {
            "slug": slug,
            "title": task["task_id"].replace("-", " ").title(),
            "site": task["site"],
            "goal": task["goal"],
        }
        if not discovery:
            payload["input_schema"] = task["input_schema"]
            payload["output_schema"] = task["output_schema"]
        create = await client.post("/v1/workflows", json=payload)
        if create.status_code not in (201, 409):
            print(
                f"[setup] {task['task_id']}: create failed "
                f"({create.status_code}) {create.text[:200]}",
                flush=True,
            )
            return None
        wf_resp = await client.get(f"/v1/workflows/{slug}")

    wf = _json_body(wf_resp)
    if args.skip_compile_if_active and wf.get("active_contract_id"):
        contracts = await client.get(f"/v1/workflows/{slug}/contracts")
        active = next(
            (c for c in (contracts.json() or []) if c.get("status") == "active"), None
        )
        if active is not None:
            print(
                f"[setup] {task['task_id']}: reusing active contract "
                f"v{active['version']} (method={active['method']})",
                flush=True,
            )
            return {"method": active["method"], "version": active["version"]}

    record = base_record(task, "compile")
    engine = task["compile_engine"]

    async def _compile() -> dict[str, Any] | None:
        t0 = time.perf_counter()
        try:
            resp = await client.post(
                f"/v1/workflows/{slug}/compile",
                json={"engine": engine, "activate": True},
                timeout=COMPILE_TIMEOUT_S,
            )
            record["http_status"] = resp.status_code
            record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            body = _json_body(resp)
            job = body.get("job") or {}
            contract = body.get("contract")
            record["h_session_id"] = job.get("h_session_id")
            if resp.status_code == 200 and contract and job.get("status") == "completed":
                record["ok"] = True
                record["contract_version"] = contract.get("version")
                # Compile cost is not exposed by the API: mock is $0, live unknown.
                record["cost_usd"] = 0.0 if job.get("engine") == "mock" else None
                record["error_class"] = "none"
                return {"method": contract.get("method"), "version": contract.get("version")}
            record["error"] = (job.get("error") or resp.text)[:2000]
        except httpx.TimeoutException:
            record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            record["error"] = f"client timeout after {COMPILE_TIMEOUT_S:.0f}s"
            record["error_class"] = "timeout"
        except Exception as e:
            record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
            record["error"] = f"{type(e).__name__}: {e}"
        return None

    ctx: dict[str, Any] | None
    if discovery:
        # Discovery compiles cost an H session in live mode → semaphore + budget.
        if h_mode == "live" and not rec.reserve_agent_op(f"compile:{task['task_id']}"):
            print(f"[setup] {task['task_id']}: SKIPPED compile (budget)", flush=True)
            return None
        async with sem:
            ctx = await _compile()
    else:
        ctx = await _compile()

    rec.record("setup", record)
    if ctx is not None:
        print(
            f"[setup] {task['task_id']}: compiled v{ctx['version']} "
            f"method={ctx['method']} (engine={engine})",
            flush=True,
        )
    else:
        print(f"[setup] {task['task_id']}: compile FAILED — {record['error']}", flush=True)
    return ctx


async def wave1_http(
    client: httpx.AsyncClient,
    tasks: list[dict[str, Any]],
    ctxs: dict[str, dict[str, Any]],
    rec: Recorder,
    args: argparse.Namespace,
) -> None:
    http_tasks = [
        t for t in tasks if t["expected_path"] == "http" and t["task_id"] in ctxs
    ]

    async def sample(task: dict[str, Any]) -> None:
        n = task["http_samples"] or args.http_samples
        for i in range(n):
            await do_run(
                client,
                task,
                "W1",
                rec,
                run_input=task["run_input"],
                timeout=HTTP_SAMPLE_TIMEOUT_S,
                label=f"sample {i + 1}/{n}",
            )

    await asyncio.gather(*(sample(t) for t in http_tasks))


async def wave23_agent(
    client: httpx.AsyncClient,
    tasks: list[dict[str, Any]],
    ctxs: dict[str, dict[str, Any]],
    rec: Recorder,
    sem: asyncio.Semaphore,
    args: argparse.Namespace,
    wave: str,
) -> None:
    jobs: list[tuple[dict[str, Any], str | None, str]] = []
    for task in tasks:
        if task["task_id"] not in ctxs:
            continue
        if task["agent"]:
            for i in range(args.agent_runs):
                jobs.append((task, None, f"run {i + 1}/{args.agent_runs}"))
        if ctxs[task["task_id"]]["method"] == "hybrid":
            jobs.append((task, "agent", "force-agent"))

    async def one(task: dict[str, Any], force: str | None, label: str) -> None:
        async with sem:
            if not rec.reserve_agent_op(f"{wave}:{task['task_id']}:{label}"):
                print(f"[{wave}] {task['task_id']} {label}: SKIPPED (budget)", flush=True)
                return
            timeout = float(task.get("timeout_s") or DEFAULT_RUN_TIMEOUT_S)
            await do_run(
                client,
                task,
                wave,
                rec,
                run_input=task["run_input"],
                force_path=force,
                timeout=timeout,
                label=label,
            )

    await asyncio.gather(*(one(t, f, lbl) for t, f, lbl in jobs))


async def wave4_burst(
    client: httpx.AsyncClient,
    task: dict[str, Any],
    rec: Recorder,
) -> None:
    print("[W4] hn-top-baseline: 20 concurrent HTTP runs (single burst)", flush=True)
    await asyncio.gather(
        *(
            do_run(
                client,
                task,
                "W4",
                rec,
                run_input=task["run_input"],
                timeout=HTTP_SAMPLE_TIMEOUT_S,
                label=f"burst {i + 1}/20",
            )
            for i in range(20)
        )
    )


def _p50(values: list[float]) -> float:
    return float(statistics.median(values))


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return float(ordered[int(0.95 * (len(ordered) - 1))])


def _fmt_lat(runs: list[dict[str, Any]]) -> str:
    vals = [float(r["latency_ms"]) for r in runs]
    if not vals:
        return "—"
    return f"{_p50(vals):.0f} / {_p95(vals):.0f}"


def _fmt_cost(runs: list[dict[str, Any]]) -> str:
    costs = [r["cost_usd"] for r in runs if r["cost_usd"] is not None]
    if not costs:
        return "—"
    return f"${statistics.fmean(costs):.4f}"


def _cohort(task: dict[str, Any]) -> str:
    if task["expected_path"] == "http":
        return "http_api"
    if task["js_profile"] in JS_HEAVY_PROFILES:
        return "agent_js_heavy"
    return "agent_other"


def build_report(
    args: argparse.Namespace,
    h_mode: str,
    tasks: list[dict[str, Any]],
    ctxs: dict[str, dict[str, Any]],
    rec: Recorder,
) -> str:
    runs = [r for r in rec.records if r["kind"] == "run"]
    compiles = [r for r in rec.records if r["kind"] == "compile"]
    w4 = [r for r, w in zip(rec.records, rec.record_waves) if w == "W4"]
    agent_runs = [r for r in runs if r["path"] == "agent" and r["ok"]]
    http_runs = [r for r in runs if r["path"] == "http"]
    trap_runs = [r for r in runs if r.get("note") == "TRAP"]
    core_tasks = [t for t in tasks if not t["extra"]]
    lines: list[str] = []
    add = lines.append

    add("# API H — hard eval report")
    add("")
    add(
        f"Generated {now_iso()} · base_url `{args.base_url}` · h_mode `{h_mode}` · "
        f"K={args.h_concurrency} · agent ops {rec.agent_ops}/{args.max_agent_runs_total} · "
        f"cost ${rec.total_cost_usd:.4f}/${args.max_cost_usd:.2f}"
    )
    add("")

    # Table 1 — per-task results
    add("## Table 1 — per-task results")
    add("")
    add(
        "| task_id | js | expected | diff | compile | runs ok/total | paths | "
        "latency p50/p95 ms | mean cost | error classes |"
    )
    add("|---|---|---|---|---|---|---|---|---|---|")
    for task in tasks:
        tid = task["task_id"]
        t_compiles = [c for c in compiles if c["task_id"] == tid]
        t_runs = [r for r in runs if r["task_id"] == tid]
        if t_compiles:
            compile_cell = "ok" if any(c["ok"] for c in t_compiles) else "FAIL"
        elif tid in ctxs:
            compile_cell = "reused"
        else:
            compile_cell = "—"
        paths = Counter(r["path"] for r in t_runs if r["path"])
        errs = Counter(r["error_class"] for r in t_runs if r["error_class"] != "none")
        add(
            f"| {tid} | {task['js_profile']} | {task['expected_path']} | "
            f"{task['difficulty']} | {compile_cell} | "
            f"{sum(1 for r in t_runs if r['ok'])}/{len(t_runs)} | "
            f"{dict(paths) or '—'} | {_fmt_lat(t_runs)} | {_fmt_cost(t_runs)} | "
            f"{dict(errs) or '—'} |"
        )
    add("")

    # Table 2 — cohorts
    add("## Table 2 — cohorts")
    add("")
    add(
        "Cohorts: `http_api` (expected http), `agent_js_heavy` "
        "(csr|spa|scroll|consent|dynamic|softbot), `agent_other` (remaining agent tasks)."
    )
    add("")
    add("| cohort | tasks | runs | ok | success rate | latency p50/p95 ms | mean cost |")
    add("|---|---|---|---|---|---|---|")
    cohort_rates: dict[str, float | None] = {}
    for name in ("http_api", "agent_js_heavy", "agent_other"):
        c_tasks = [t for t in tasks if _cohort(t) == name]
        ids = {t["task_id"] for t in c_tasks}
        c_runs = [r for r in runs if r["task_id"] in ids]
        ok_n = sum(1 for r in c_runs if r["ok"])
        rate = ok_n / len(c_runs) if c_runs else None
        cohort_rates[name] = rate
        add(
            f"| {name} | {len(c_tasks)} | {len(c_runs)} | {ok_n} | "
            f"{f'{rate:.0%}' if rate is not None else '—'} | {_fmt_lat(c_runs)} | "
            f"{_fmt_cost(c_runs)} |"
        )
    add("")

    # Table 3 — JS failure taxonomy
    add("## Table 3 — JS failure taxonomy (failed runs by error_class × js_profile)")
    add("")
    failed = [r for r in runs if r["error_class"] not in ("none",)]
    profiles = sorted({r["js_profile"] for r in runs})
    classes = ["schema", "empty", "blocked", "timeout", "hydration", "other"]
    add("| error_class | " + " | ".join(profiles) + " | total |")
    add("|---|" + "---|" * (len(profiles) + 1))
    for cls in classes:
        row = [str(sum(1 for r in failed if r["error_class"] == cls and r["js_profile"] == p)) for p in profiles]
        total = sum(1 for r in failed if r["error_class"] == cls)
        add(f"| {cls} | " + " | ".join(row) + f" | {total} |")
    add("")

    # Table 4 — amortization
    add("## Table 4 — amortization (20× HN HTTP measured vs counterfactual agent)")
    add("")
    w4_ok = [r for r in w4 if r["ok"]]
    w4_total_ms = sum(r["latency_ms"] for r in w4)
    w4_total_cost = sum(r["cost_usd"] or 0.0 for r in w4)
    add("| variant | runs | total latency ms | total cost |")
    add("|---|---|---|---|")
    add(
        f"| measured: 20× HN via HTTP (W4 burst) | {len(w4)} ({len(w4_ok)} ok) | "
        f"{w4_total_ms} | ${w4_total_cost:.4f} |"
    )
    if agent_runs:
        mean_ms = statistics.fmean(float(r["latency_ms"]) for r in agent_runs)
        agent_costs = [r["cost_usd"] for r in agent_runs if r["cost_usd"] is not None]
        mean_cost = statistics.fmean(agent_costs) if agent_costs else 0.0
        add(
            f"| counterfactual: 20× agent (measured means: {mean_ms:.0f} ms, "
            f"${mean_cost:.4f}/run) | 20 | {20 * mean_ms:.0f} | {20 * mean_cost:.4f} |"
        )
    else:
        add("| counterfactual: 20× agent | 20 | <!-- FILLME --> | <!-- FILLME --> |")
    add("")

    # Gates
    add("## Gates")
    add("")
    core_compile_ok = all(
        tid in ctxs
        for tid in (t["task_id"] for t in core_tasks)
    )
    w4_5xx = [
        r
        for r in w4
        if (r["http_status"] or 0) >= 500
        or ("database" in (r["error"] or "").lower())
        or ("locked" in (r["error"] or "").lower())
    ]
    disc_tasks = [t for t in tasks if t["input_schema"] is None]
    disc_ok = bool(disc_tasks) and all(t["task_id"] in ctxs for t in disc_tasks)
    http_lat = [float(r["latency_ms"]) for r in http_runs if r["ok"]]
    js_rate = cohort_rates.get("agent_js_heavy")
    incomplete = [
        r
        for r in runs
        if (r["ok"] and r["path"] is None)
        or (not r["ok"] and r["error_class"] == "none")
    ]
    budget_ok = (
        rec.agent_ops <= args.max_agent_runs_total
        and rec.total_cost_usd <= args.max_cost_usd
    )
    gates: list[tuple[str, str, bool]] = [
        ("G1", "server healthy at W0 (`GET /health` ok, h_mode recorded)", True),
        (
            "G2",
            "all selected core tasks (1-15) hold an active contract (compiled or reused)",
            core_compile_ok,
        ),
        (
            "G3",
            "no TRAP: every run on an http-expected task served with path=http",
            not trap_runs,
        ),
        (
            "G4",
            "http path p95 latency < 5000 ms",
            bool(http_lat) and _p95(http_lat) < 5000,
        ),
        (
            "G5",
            "discovery compiles (quotes-js-rendered, quotes-scroll) produced contracts",
            disc_ok,
        ),
        (
            "G6",
            "agent_js_heavy cohort success rate ≥ 50%",
            js_rate is not None and js_rate >= 0.5,
        ),
        ("G7", "W4 burst (20 concurrent): zero 5xx / DB-lock errors", not w4_5xx),
        (
            "G8",
            f"budget respected (agent ops ≤ {args.max_agent_runs_total}, "
            f"cost ≤ ${args.max_cost_usd:.2f})",
            budget_ok,
        ),
        (
            "G9",
            "record integrity: every ok run has a path; every failed run is classified",
            not incomplete,
        ),
    ]
    add("| gate | definition | result |")
    add("|---|---|---|")
    for gid, definition, passed in gates:
        add(f"| {gid} | {definition} | {'PASS' if passed else 'FAIL'} |")
    add("")

    # Narrative
    add("## Narrative")
    add("")
    n_http_no_h = sum(1 for r in http_runs if r["ok"] and not r["h_session_id"])
    add("**1. Which tasks graduate to pure HTTP, and does the HTTP path avoid H sessions?**")
    http_ids = sorted({r["task_id"] for r in http_runs if r["ok"]})
    if http_runs:
        add(
            f"Tasks served over HTTP: {', '.join(http_ids) or 'none'}. "
            f"{n_http_no_h}/{len(http_runs)} http-path runs completed with no H session "
            f"attached — the contract, not the agent, does the work."
        )
    else:
        add("<!-- FILLME --> (no http runs recorded)")
    add("")
    add("**2. Does the router honor expected paths (any TRAP events)?**")
    add(
        f"{len(trap_runs)} TRAP run(s) — http-expected tasks that fell through to the "
        f"agent path." + (" None observed; routing held." if not trap_runs else "")
    )
    add("")
    add("**3. How do JS-heavy profiles fare on the agent path vs other agent tasks?**")
    other_rate = cohort_rates.get("agent_other")
    if js_rate is not None or other_rate is not None:
        add(
            f"agent_js_heavy success {f'{js_rate:.0%}' if js_rate is not None else '—'} vs "
            f"agent_other {f'{other_rate:.0%}' if other_rate is not None else '—'} "
            f"(Table 2)."
        )
    else:
        add("<!-- FILLME --> (no agent runs executed)")
    add("")
    add("**4. What failure classes dominate on JS-heavy tasks?**")
    js_failed = Counter(
        r["error_class"] for r in failed if r["js_profile"] in JS_HEAVY_PROFILES
    )
    if js_failed:
        add(
            "JS-heavy failures by class: "
            + ", ".join(f"{k}={v}" for k, v in js_failed.most_common())
            + " (Table 3)."
        )
    else:
        add("No JS-heavy failures recorded." if runs else "<!-- FILLME -->")
    add("")
    add("**5. Did schema discovery (the JS litmus) produce usable contracts?**")
    disc_lines: list[str] = []
    for t in disc_tasks:
        compiled = t["task_id"] in ctxs
        t_ok_runs = sum(1 for r in runs if r["task_id"] == t["task_id"] and r["ok"])
        disc_lines.append(
            f"{t['task_id']}: compile {'ok' if compiled else 'FAIL'}, "
            f"{t_ok_runs} ok run(s)"
        )
    add("; ".join(disc_lines) + "." if disc_lines else "<!-- FILLME -->")
    add("")
    add("**6. What does HTTP amortization save vs 20 counterfactual agent runs?**")
    if agent_runs and w4:
        mean_ms = statistics.fmean(float(r["latency_ms"]) for r in agent_runs)
        add(
            f"Measured: 20 HTTP runs took {w4_total_ms} ms total at "
            f"${w4_total_cost:.4f}; 20 agent runs would take ~{20 * mean_ms:.0f} ms "
            f"at measured mean agent cost (Table 4)."
        )
    else:
        add("<!-- FILLME --> (need both W4 burst data and ≥1 ok agent run)")
    add("")
    add("**7. Does the system stay correct under concurrency and within budget?**")
    add(
        f"W4: {len(w4_ok)}/{len(w4)} ok, {len(w4_5xx)} 5xx/DB errors. Budget: "
        f"{rec.agent_ops}/{args.max_agent_runs_total} agent ops, "
        f"${rec.total_cost_usd:.4f}/${args.max_cost_usd:.2f} spent"
        + (
            f"; {len(rec.skipped_ops)} op(s) skipped when the budget guard tripped: "
            + ", ".join(rec.skipped_ops)
            if rec.skipped_ops
            else "; no ops skipped."
        )
    )
    add("")

    add("## Parallelism note")
    add("")
    add(
        f"H agent sessions were capped at K={args.h_concurrency} concurrent "
        f"(`--h-concurrency`), in line with H's multi-agent guidance: "
        f"{MULTI_AGENT_GUIDANCE_URL}. Discovery compiles share the same semaphore "
        f"since they consume a session in live mode."
    )
    add("")
    if rec.skipped_ops:
        add("## Budget note")
        add("")
        add(
            "Budget guard stopped launching new agent ops after "
            f"{rec.agent_ops} op(s) / ${rec.total_cost_usd:.4f}. Skipped: "
            + ", ".join(rec.skipped_ops)
        )
        add("")
    return "\n".join(lines)


def select_tasks(spec: str) -> list[dict[str, Any]]:
    if spec.strip().lower() == "all":
        return list(TASKS)
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    by_id = {t["task_id"]: t for t in TASKS}
    unknown = [w for w in wanted if w not in by_id]
    if unknown:
        raise SystemExit(f"unknown task ids: {', '.join(unknown)}")
    return [by_id[w] for w in wanted]


async def main_async(args: argparse.Namespace) -> int:
    tasks = select_tasks(args.tasks)
    core = [t for t in tasks if not t["extra"]]
    extras = [t for t in tasks if t["extra"]]
    rec = Recorder(Path(args.out), args.max_agent_runs_total, args.max_cost_usd)
    sem = asyncio.Semaphore(args.h_concurrency)

    async with httpx.AsyncClient(
        base_url=args.base_url, timeout=HTTP_SAMPLE_TIMEOUT_S
    ) as client:
        # W0 — health
        try:
            health = await client.get("/health")
            body = _json_body(health)
            if health.status_code != 200 or not body.get("ok"):
                print(f"[W0] health check failed: {health.status_code} {health.text[:200]}")
                return 1
        except Exception as e:
            print(f"[W0] server unreachable at {args.base_url}: {e}")
            return 1
        h_mode = str(body.get("h_mode", "mock"))
        print(f"[W0] health ok, h_mode={h_mode}", flush=True)

        # Setup — create + compile (all selected tasks; extras' compiles are mock/free)
        ctxs: dict[str, dict[str, Any]] = {}
        for task in tasks:
            ctx = await setup_task(client, task, rec, sem, args, h_mode)
            if ctx is not None:
                ctxs[task["task_id"]] = ctx

        # W1 — HTTP sampling
        await wave1_http(client, core, ctxs, rec, args)

        # W2+W3 — agent runs for tasks 1-15
        await wave23_agent(client, core, ctxs, rec, sem, args, "W2W3")

        # W4 — concurrency burst on hn-top-baseline
        burst_task = next((t for t in tasks if t["task_id"] == "hn-top-baseline"), None)
        if burst_task is not None and burst_task["task_id"] in ctxs:
            await wave4_burst(client, burst_task, rec)

        # Extras — only if budget remains after 1-15
        if extras:
            if rec.budget_ok():
                await wave23_agent(client, extras, ctxs, rec, sem, args, "EXTRA")
            else:
                for t in extras:
                    rec.skipped_ops.append(f"EXTRA:{t['task_id']}")
                print("[EXTRA] skipped — budget exhausted after tasks 1-15", flush=True)

    report = build_report(args, h_mode, tasks, ctxs, rec)
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    rec.close()
    print(
        f"\nDone. {len(rec.records)} records → {args.out}; report → {args.report}. "
        f"Agent ops {rec.agent_ops}/{args.max_agent_runs_total}, "
        f"cost ${rec.total_cost_usd:.4f}/${args.max_cost_usd:.2f}.",
        flush=True,
    )
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="API H hard eval battery (REST-only; server must already be running)"
    )
    p.add_argument("--base-url", default="http://127.0.0.1:8000")
    p.add_argument("--tasks", default="all", help="all | comma-separated task_ids")
    p.add_argument("--http-samples", type=int, default=20)
    p.add_argument("--agent-runs", type=int, default=1)
    p.add_argument("--h-concurrency", type=int, default=2)
    p.add_argument("--max-agent-runs-total", type=int, default=40)
    p.add_argument("--max-cost-usd", type=float, default=5.0)
    p.add_argument("--out", default="data/eval_results.jsonl")
    p.add_argument("--report", default="data/eval_report.md")
    p.add_argument("--skip-compile-if-active", action="store_true")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(asyncio.run(main_async(parse_args())))
