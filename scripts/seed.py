"""Seed: default workspace + hn-top-stories workflow, compiled + activated.

Run from repo root:  uv run python scripts/seed.py
Idempotent — an existing workflow is recompiled (contract version bumps).
"""

import asyncio
import json
import sys
from pathlib import Path

# Allow running as a plain script from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, models, schemas  # noqa: E402
from app.services import compiler, contract_store  # noqa: E402

SLUG = "hn-top-stories"

INPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 30}
    },
}

OUTPUT_SCHEMA: dict = {
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

CURL_EXAMPLES = f"""
Try it (server must be running: uv run uvicorn app.main:app --port 8000):

  curl -s http://127.0.0.1:8000/health | jq

  curl -s -X POST http://127.0.0.1:8000/v1/workflows/{SLUG}/compile \\
    -H 'content-type: application/json' \\
    -d '{{"engine": "auto", "activate": true}}' | jq

  curl -s -X POST http://127.0.0.1:8000/v1/workflows/{SLUG}/run \\
    -H 'content-type: application/json' \\
    -d '{{"input": {{"limit": 5}}}}' | jq

  curl -s -X POST http://127.0.0.1:8000/v1/workflows/{SLUG}/run \\
    -H 'content-type: application/json' \\
    -d '{{"input": {{"limit": 3}}, "force_path": "agent"}}' | jq

  curl -s http://127.0.0.1:8000/v1/workflows/{SLUG}/openapi.json | jq

Or run the whole demo:  ./scripts/demo_curl.sh
"""


async def main() -> None:
    db.init_db()
    session = db.SessionLocal()
    try:
        workspace = contract_store.get_or_create_default_workspace(session)
        session.commit()

        workflow = contract_store.get_workflow(session, SLUG)
        if workflow is None:
            workflow = models.Workflow(
                workspace_id=workspace.id,
                slug=SLUG,
                title="Hacker News top stories",
                site="https://news.ycombinator.com",
                goal="Return top N front-page stories with rank, title, url, points",
                input_schema_json=json.dumps(INPUT_SCHEMA),
                output_schema_json=json.dumps(OUTPUT_SCHEMA),
            )
            session.add(workflow)
            session.commit()
            print(f"Created workflow {SLUG} ({workflow.id})")
        else:
            print(f"Workflow {SLUG} exists ({workflow.id}) — recompiling")

        resp = await compiler.compile_workflow(
            session, workflow, schemas.CompileRequest(engine="auto", activate=True)
        )
        session.commit()

        print(f"Compile job {resp.job.id}: {resp.job.status} (engine={resp.job.engine})")
        if resp.contract is not None:
            print(
                f"Contract v{resp.contract.version} "
                f"({resp.contract.status}, method={resp.contract.method}, "
                f"id={resp.contract.id})"
            )
        else:
            print(f"No contract produced — job error: {resp.job.error}")

        print(CURL_EXAMPLES)
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
