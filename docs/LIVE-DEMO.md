# Live H demo — Craigslist via schema discovery

Runnable sequence for a fresh machine with a real H Company API key. This exercises the
full product loop: create a workflow from **site + goal only**, let compile **discover**
the schemas with one H Computer-Use exploration session, then serve every subsequent
request from the stored contract.

## 1. Setup (once per machine)

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/gurul/apiH.git && cd apiH
uv sync
uv add hai-agents          # H SDK (1.0.6 at time of writing) — only needed for live mode
cp .env.example .env
```

Edit `.env`:

```bash
HAI_API_KEY=hk-your-key-here
API_H_MOCK_H=false
```

Start the server (settings are read at boot — restart after editing `.env`):

```bash
uv run uvicorn app.main:app --port 8000
```

Confirm live mode — this must say `"h_mode": "live"`, otherwise you're still on the mock:

```bash
curl -s http://127.0.0.1:8000/health | jq
```

## 2. Create the workflow — no schemas, just intent

`{{limit}}` in the goal automatically becomes a run input (integer, default 5).
Any other `{{var}}` placeholder becomes a string input.

```bash
curl -s -X POST http://127.0.0.1:8000/v1/workflows \
  -H 'content-type: application/json' \
  -d '{
    "slug": "craigslist-apartments",
    "title": "Craigslist SF Bay apartments",
    "site": "https://sfbay.craigslist.org/search/apa",
    "goal": "Return the top {{limit}} apartment listings with title, price and url"
  }' | jq
```

Note `output_schema: {}` in the response — nothing has been figured out yet.

## 3. Compile — the one H exploration run

This triggers a real H Computer-Use session that opens the site, achieves the goal once,
and returns a sample. Expect **30–120 s**. From the sample, API H infers the
`output_schema` (fields present-but-null in some listings become optional), derives the
`input_schema` from the goal placeholders, persists both onto the workflow, and stores
contract v1 with the sample kept as `compile_meta.sample_answer`.

```bash
curl -s -X POST http://127.0.0.1:8000/v1/workflows/craigslist-apartments/compile \
  -H 'content-type: application/json' \
  -d '{"engine": "auto", "activate": true}' | jq
```

Check what was discovered:

```bash
curl -s http://127.0.0.1:8000/v1/workflows/craigslist-apartments | jq '.input_schema, .output_schema'
```

## 4. Run — subsequent requests use the stored contract

No re-discovery: the contract compiled in step 3 is loaded from SQLite on every run.
Craigslist has no known public API, so its contract is `method: agent` — **each run
re-triggers H** (30–120 s, real agent cost). `meta` shows `path: "agent"`, wall-clock
`latency_ms`, and the `h_session_id`.

```bash
curl -s -X POST http://127.0.0.1:8000/v1/workflows/craigslist-apartments/run \
  -H 'content-type: application/json' \
  -d '{"input": {"limit": 5}}' | jq
```

Contrast with the HTTP-graduated path (seed it first with
`uv run python scripts/seed.py`): the HN workflow answers in well under a second with no
H call —

```bash
curl -s -X POST http://127.0.0.1:8000/v1/workflows/hn-top-stories/run \
  -H 'content-type: application/json' \
  -d '{"input": {"limit": 5}}' | jq '.meta'
```

## 5. If the schema came out wrong

Recompile — a fresh exploration run, bumped contract version, previous version
deprecated (or pass explicit schemas when creating the workflow to skip discovery
entirely):

```bash
curl -s -X POST http://127.0.0.1:8000/v1/workflows/craigslist-apartments/recompile \
  -H 'content-type: application/json' \
  -d '{"engine": "auto", "activate": true}' | jq
```

## Caveats

- If H's answer on a run doesn't match the discovered schema, the run fails validation
  and returns **502** rather than bad data — by design. Recompile if the site changed.
- In mock mode (`API_H_MOCK_H=true` or no key) discovery infers from the deterministic
  mock answer, so the schema is a placeholder. Real discovery needs live H.
- Craigslist ToS / robots are your responsibility; agent runs cost real money and real
  seconds — the contract + router exists precisely so you pay that only when there is
  no cheaper path.
