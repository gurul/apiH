# EVAL-SPEC.md — hard eval suite (JS-heavy battery) build contract

Three agents build this in parallel. Deliverables: new HTTP mappers + compiler
specializations (agent A), `scripts/hard_eval.py` (agent B), offline regression tests +
doc touch-ups (agent C). Do NOT rebuild the product. Read `docs/SPEC.md`,
`docs/INTERFACES.md` and the existing code first.

## Product changes (agent A) — app/services

### base.py

- `ALLOWED_HOSTS` becomes: `{"hacker-news.firebaseio.com", "wttr.in", "openlibrary.org",
  "countries.trevorblades.com"}` (SSRF allowlist — still enforced on every URL).
- Add `async def post_json(url: str, json_body: dict) -> object` — same allowlist check,
  singleton client, `raise_for_status`, `.json()`.

### hn_firebase.py

Mapper `hn_firebase_v0` gains feed support: `feed = input.get("feed")` in
`{None, "top", "ask", "show"}` → `topstories.json | askstories.json | showstories.json`
(invalid feed → ValueError). Everything else unchanged.

### New mapper modules (each `@register_mapper`, imported in `__init__.py`)

- `wttr.py` — `wttr_v0`: `city = input.get("city", "London")`, validate
  `^[A-Za-z .-]{1,40}$`, GET `https://wttr.in/{quote(city)}?format=j1`, map
  `current_condition[0]` → `{"temp_C": str, "humidity": str, "weather_desc":
  cc["weatherDesc"][0]["value"]}`.
- `openlibrary.py` — `openlibrary_search_v0`: `q = input.get("q", "")` (non-empty str),
  `limit = int(input.get("limit", 5))` clamp 1..20, GET
  `https://openlibrary.org/search.json?q={quote_plus(q)}&limit={limit}` → `{"works":
  [{"title": str, "authors": doc.get("author_name") or [], "year":
  doc.get("first_publish_year")  # int|None, "key": str}]}`.
- `graphql_countries.py` — `graphql_countries_v0`: `code = input.get("continent","EU")`
  validate `^[A-Z]{2}$`, `limit` clamp 1..20, POST `https://countries.trevorblades.com/`
  body `{"query": "query($c: ID!){ continent(code:$c){ countries { name } } }",
  "variables": {"c": code}}` → `{"countries": [name, ...][:limit]}`.

### compiler.py — generalize the one-off HN specialization

```python
SPECIALIZATIONS: dict[str, dict] = {
    # hostname → {"mapper": str, "description": str, "steps": [...] }
    "news.ycombinator.com": <existing HN block>,
    "wttr.in": {...}, "openlibrary.org": {...}, "countries.trevorblades.com": {...},
}
def find_specialization(workflow) -> dict | None   # urlparse(site).hostname lookup;
                                                   # slug startswith "hn" also → HN
```

`build_contract_body` keeps its signature (`hn: bool` param stays for backcompat,
meaning "specialized") but gains `specialization: dict | None = None`; when set (or
hn=True → HN spec) the http block comes from the specialization and method="hybrid".
`compile_workflow` calls `find_specialization` instead of `is_hn` (keep `is_hn` working).
Agent prompt for specialized non-HN sites: the generic goal-based prompt (unchanged).

## Eval harness (agent B) — scripts/hard_eval.py

Pure-stdlib + httpx client script driving the REST API (never imports app internals
except nothing — HTTP only). CLI (argparse):

```
--base-url http://127.0.0.1:8000  --tasks all|comma-list  --http-samples 20
--agent-runs 1  --h-concurrency 2  --max-agent-runs-total 40  --max-cost-usd 5.0
--out data/eval_results.jsonl  --report data/eval_report.md  --skip-compile-if-active
```

### Task registry (TASKS: list[dict]) — all 19, exactly these ids

Fields: task_id, slug, site, goal, js_profile, expected_path, difficulty,
input_schema|None, output_schema|None (None,None → DISCOVERY compile),
compile_engine ("mock" for explicit-schema tasks, "auto" for discovery),
run_input, agent (True if agent/hybrid-force runs wanted), http_samples override.

1. `hn-top-baseline` slug hn-top-stories (reuse if exists else create+compile) site
   https://news.ycombinator.com goal "Return the top {{limit}} front-page stories" —
   js api, expected http, diff 1, HN schemas (stories rank/title/url/points),
   run_input {"limit":10}, http_samples=args.http_samples.
2. `hn-ask-show` slug hn-ask-show, same site, goal "Return the top {{limit}} Show HN
   stories from the Show feed", input_schema adds feed {"type":"string","default":"show"},
   HN output schema, run_input {"limit":5,"feed":"show"}, expected http (hybrid), diff 2.
3. `wikipedia-toc` site https://en.wikipedia.org/wiki/Web_scraping goal "Read the
   article. Return the lead paragraph text and the section outline (H2/H3 headings in
   order with level 2 or 3)". schema {"lead": str, "sections":[{"title": str, "level":
   int}]} required lead+sections, js static, expected agent, diff 2.
4. `github-repo-meta` site https://github.com/hcompai/hai-agents-python goal "Report
   full_name, stars, forks, open_issues, default_branch and latest_release_tag (null if
   no release). Counts as integers (expand K/1.2k notation)". schema per §5 sketch
   (latest_release_tag nullable → NOT in required), js spa, agent, diff 3.
5. `craigslist-sf-bikes` site https://sfbay.craigslist.org/search/bia?max_price=500
   goal "Return {{limit}} bike listings under $500: title, price, url, location
   (location may be empty string)". schema listings[] title/price/url required +
   location optional, run_input {"limit":5}, js softbot, agent, diff 4.
6. `hn-algolia-ui` site https://hn.algolia.com goal "Use the search box to search for
   'Show HN'. Return the first {{limit}} results: title, url (null if none), points
   (integer), created_at". hits[] title/points/created_at required, js csr, agent, diff 3.
7. `quotes-js-rendered` site https://quotes.toscrape.com/js goal "Return the first
   {{limit}} quotes visible after the page renders: text, author, tags (list of
   strings)". **DISCOVERY** (no schemas, compile_engine auto), run_input {"limit":5},
   js csr, agent, diff 3. THE JS LITMUS — compile first.
8. `quotes-scroll` site https://quotes.toscrape.com/scroll goal "Scroll down until at
   least {{limit}} quotes have loaded, then return them: text, author, tags. No
   duplicates." **DISCOVERY**, run_input {"limit":10}, js scroll, agent, diff 4. LITMUS.
9. `weather-wttr` site https://wttr.in goal "Return current weather for {{city}}:
   temp_C, humidity, weather_desc" schemas matching wttr_v0 mapper, input city default
   London, run_input {"city":"London"}, js api, expected http (TRAP: record if path
   != http), diff 1, http_samples=10.
10. `openlibrary-search` site https://openlibrary.org goal "Search for {{q}} and return
    {{limit}} works: title, authors, year, key" schemas matching mapper, run_input
    {"q":"foundation asimov","limit":5}, js api, http, diff 2, http_samples=5.
11. `books-toscrape` site https://books.toscrape.com goal "From catalogue page 1 return
    {{limit}} books: title, price, rating (one|two|...|five as written), in_stock
    (boolean)". books[] all required, run_input {"limit":5}, js static, agent, diff 2.
12. `demoqa-dynamic` site https://the-internet.herokuapp.com/dynamic_loading/2 goal
    "Click Start, wait for the loading to finish, and return status ('ok') and the text
    that appears". schema {"status": str, "text": str} both required, js dynamic,
    agent, diff 4.
13. `spa-nav` site https://demoqa.com/books goal "In the Book Store application open
    the first book in the list and return its title, author and publisher". schema
    {"title","author","publisher"} all required str, js spa, agent, diff 4.
14. `cookie-consent-content` site https://www.theguardian.com/europe goal "If a cookie
    consent dialog appears, reject or dismiss non-essential cookies. Then return the
    main headline and 3 other visible headlines". schema {"headline": str, "others":
    [str]} required both, js consent, agent, diff 4.
15. `github-issues-spa` site https://github.com/hcompai/hai-agents-python/issues goal
    "Return {{limit}} open issues: number (integer), title, author, labels (list of
    strings, may be empty)". issues[] number/title/author required, run_input
    {"limit":5}, js spa, agent, diff 4.
16. `hn-item-thread` site https://news.ycombinator.com/item goal "Open the current top
    story's comment page and return story_title plus the top {{limit}} comments: author
    and first sentence of text". schema {"story_title": str, "comments":[{"author": str,
    "text": str}]}, run_input {"limit":3}, js static, agent, diff 3. EXTRA (only if
    budget remains).
17. `multi-step-js-chain` site https://quotes.toscrape.com/js goal "Read the first
    quote's author on the JS-rendered page, then search Wikipedia for that author and
    return the author name and the first sentence of their Wikipedia article." schema
    {"author": str, "wiki_lead": str} required, js csr, agent, diff 5. EXTRA.
18. `softwall-probe` site https://www.ticketmaster.com goal "Open the homepage. If a
    bot check, challenge or access-denied page appears, return status 'blocked' with
    detail. If it loads, return status 'ok' and the page title." schema {"status": str,
    "title": str|null optional, "detail": str} required status+detail, js softbot,
    agent, diff 5. EXTRA. Hard timeout 120s client-side → error_class timeout.
19. `graphql-countries` site https://countries.trevorblades.com goal "Return {{limit}}
    country names on continent {{continent}}" schemas matching mapper, run_input
    {"continent":"EU","limit":5}, js graphql, http, diff 1, http_samples=5.

### Waves (asyncio)

- W0: GET /health (record h_mode). Server must be up; abort otherwise.
- Setup: for each selected task: create workflow if missing (409 → ok), compile if no
  active contract or not --skip-compile-if-active. compile_engine per task; discovery
  compiles (7, 8) go through the H semaphore (they cost a session in live mode).
- W1: HTTP sampling — for tasks with expected_path http: N sequential-per-task but all
  tasks concurrently (asyncio.gather); record every run (path MUST be http; a run with
  path=agent on task 9/19 is recorded with note "TRAP").
- W2+W3: agent tasks — `asyncio.Semaphore(args.h_concurrency)`; per task agent_runs
  live runs (run_input, plus force_path="agent" ONLY for hybrid tasks 1 test each if
  budget). Client timeout 660s; task 18 timeout 120s. Respect
  --max-agent-runs-total and --max-cost-usd (sum meta.cost_usd + compile costs; stop
  launching new agent ops when exceeded, note in report).
- W4: 20 concurrent hn-top-baseline runs (asyncio.gather, single burst) — count DB/500
  errors.
- Extras (16-18) run only if budget (runs+cost) remains after 1-15.

### JSONL record (one line per compile and per run)

```
{kind: "compile"|"run", task_id, slug, site, js_profile, expected_path, difficulty,
 ok, path|null, latency_ms, cost_usd, h_session_id, contract_version, http_status,
 error_class, error, ts}
```

error_class inference: none | schema (502 with schema/output errors or health_failed
with data) | empty (health min_array/empty results) | blocked (answer/error mentions
blocked/captcha/denied or task-18 status blocked) | timeout (client timeout, H
timed_out) | hydration (empty-after-load signals on csr/scroll/dynamic tasks) | other.
Classify from the 502 errors list + response body; be honest, prefer other over guessing.

### Report (data/eval_report.md)

Tables 1-4 exactly as the master spec (per-task; cohorts http_api / agent_js_heavy
(csr|spa|scroll|consent|dynamic|softbot) / agent_other; JS failure taxonomy;
amortization: 20× HN HTTP measured total vs counterfactual 20× agent using measured
mean agent cost+latency). Gates G1-G9 with PASS/FAIL. Narrative section with the 7
required questions answered from the data (leave a `<!-- FILLME -->` marker only where
data cannot answer). Parallelism note: H sessions capped at K=2 in line with H's
multi-agent guidance (https://hub.hcompany.ai/computer-use-agents/multi-agent).
p50/p95 = statistics.quantiles style (p95 = index int(0.95*(n-1)) on sorted).

## Offline tests (agent C) — tests/

- test_new_mappers.py: respx-mocked wttr_v0, openlibrary_search_v0,
  graphql_countries_v0 (POST), hn feed ask/show; input validation errors (bad city,
  bad continent code) raise before any network.
- test_ssrf_new_hosts.py or extend existing: allowlisted hosts pass assert_host_allowed;
  evil hosts still blocked incl. for post_json.
- test_concurrency.py: 20 concurrent /run calls on the HN hybrid contract via
  httpx.AsyncClient(transport=ASGITransport(app=app)) with respx mocking Firebase →
  all 200, all path http, runs table has 20 ok rows, no exceptions.
- Keep the whole suite offline + green. Update docs/SPEC.md "HTTP API surface" note +
  README one paragraph (eval suite exists; scripts/hard_eval.py usage) — brief.

## Ethics / safety invariants (all agents)

Read-only tasks; no login, no captcha bypass; SSRF allowlist enforced on every executor
URL including POST; never log HAI_API_KEY; agent ops capped by K, count and cost.
