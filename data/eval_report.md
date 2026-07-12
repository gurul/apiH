# API H — hard eval report

Generated 2026-07-12T02:26:00+00:00 · base_url `http://127.0.0.1:8000` · h_mode `live` · K=2 · agent ops 20/22 · cost $1.2415/$2.00

## Table 1 — per-task results

| task_id | js | expected | diff | compile | runs ok/total | paths | latency p50/p95 ms | mean cost | error classes |
|---|---|---|---|---|---|---|---|---|---|
| hn-top-baseline | api | http | 1 | reused | 41/41 | {'http': 40, 'agent': 1} | 648 / 1046 | $0.0142 | — |
| hn-ask-show | api | http | 2 | reused | 21/21 | {'http': 20, 'agent': 1} | 216 / 379 | $0.0126 | — |
| wikipedia-toc | static | agent | 2 | reused | 1/1 | {'agent': 1} | 76576 / 76576 | $0.0700 | — |
| github-repo-meta | spa | agent | 3 | reused | 1/1 | {'agent': 1} | 32418 / 32418 | $0.0111 | — |
| craigslist-sf-bikes | softbot | agent | 4 | reused | 1/1 | {'agent': 1} | 103270 / 103270 | $0.0922 | — |
| hn-algolia-ui | csr | agent | 3 | reused | 1/1 | {'agent': 1} | 38186 / 38186 | $0.0195 | — |
| quotes-js-rendered | csr | agent | 3 | reused | 1/1 | {'agent': 1} | 28612 / 28612 | $0.0120 | — |
| quotes-scroll | scroll | agent | 4 | reused | 1/1 | {'agent': 1} | 78491 / 78491 | $0.0488 | — |
| weather-wttr | api | http | 1 | reused | 11/11 | {'http': 10, 'agent': 1} | 174 / 679 | $0.0241 | — |
| openlibrary-search | api | http | 2 | reused | 6/6 | {'http': 5, 'agent': 1} | 180 / 291 | $0.1618 | — |
| books-toscrape | static | agent | 2 | reused | 1/1 | {'agent': 1} | 31664 / 31664 | $0.0131 | — |
| demoqa-dynamic | dynamic | agent | 4 | reused | 1/1 | {'agent': 1} | 34320 / 34320 | $0.0229 | — |
| spa-nav | spa | agent | 4 | reused | 1/1 | {'agent': 1} | 23785 / 23785 | $0.0106 | — |
| cookie-consent-content | consent | agent | 4 | reused | 1/1 | {'agent': 1} | 111919 / 111919 | $0.0860 | — |
| github-issues-spa | spa | agent | 4 | reused | 1/1 | {'agent': 1} | 53223 / 53223 | $0.0389 | — |
| hn-item-thread | static | agent | 3 | reused | 2/2 | {'agent': 2} | 170185 / 133290 | $0.1312 | — |
| multi-step-js-chain | csr | agent | 5 | reused | 1/1 | {'agent': 1} | 98632 / 98632 | $0.0564 | — |
| softwall-probe | softbot | agent | 5 | reused | 0/1 | — | 24631 / 24631 | — | {'blocked': 1} |
| graphql-countries | graphql | http | 1 | reused | 6/6 | {'http': 5, 'agent': 1} | 64 / 219 | $0.2848 | — |

## Table 2 — cohorts

Cohorts: `http_api` (expected http), `agent_js_heavy` (csr|spa|scroll|consent|dynamic|softbot), `agent_other` (remaining agent tasks).

| cohort | tasks | runs | ok | success rate | latency p50/p95 ms | mean cost |
|---|---|---|---|---|---|---|
| http_api | 5 | 85 | 85 | 100% | 236 / 1050 | $0.0995 |
| agent_js_heavy | 11 | 11 | 10 | 91% | 38186 / 103270 | $0.0398 |
| agent_other | 3 | 4 | 4 | 100% | 104933 / 133290 | $0.0864 |

## Table 3 — JS failure taxonomy (failed runs by error_class × js_profile)

| error_class | api | consent | csr | dynamic | graphql | scroll | softbot | spa | static | total |
|---|---|---|---|---|---|---|---|---|---|---|
| schema | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| empty | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| blocked | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 1 |
| timeout | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hydration | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| other | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Table 4 — amortization (20× HN HTTP measured vs counterfactual agent)

| variant | runs | total latency ms | total cost |
|---|---|---|---|
| measured: 20× HN via HTTP (W4 burst) | 20 (20 ok) | 16722 | $0.0000 |
| counterfactual: 20× agent (measured means: 80085 ms, $0.0653/run) | 20 | 1601695 | 1.3069 |

## Gates

| gate | definition | result |
|---|---|---|
| G1 | server healthy at W0 (`GET /health` ok, h_mode recorded) | PASS |
| G2 | all selected core tasks (1-15) hold an active contract (compiled or reused) | PASS |
| G3 | no TRAP: every run on an http-expected task served with path=http | FAIL |
| G4 | http path p95 latency < 5000 ms | PASS |
| G5 | discovery compiles (quotes-js-rendered, quotes-scroll) produced contracts | PASS |
| G6 | agent_js_heavy cohort success rate ≥ 50% | PASS |
| G7 | W4 burst (20 concurrent): zero 5xx / DB-lock errors | PASS |
| G8 | budget respected (agent ops ≤ 22, cost ≤ $2.00) | PASS |
| G9 | record integrity: every ok run has a path; every failed run is classified | PASS |

## Narrative

**1. Which tasks graduate to pure HTTP, and does the HTTP path avoid H sessions?**
Tasks served over HTTP: graphql-countries, hn-ask-show, hn-top-baseline, openlibrary-search, weather-wttr. 80/80 http-path runs completed with no H session attached — the contract, not the agent, does the work.

**2. Does the router honor expected paths (any TRAP events)?**
5 TRAP run(s) — http-expected tasks that fell through to the agent path.

**3. How do JS-heavy profiles fare on the agent path vs other agent tasks?**
agent_js_heavy success 91% vs agent_other 100% (Table 2).

**4. What failure classes dominate on JS-heavy tasks?**
JS-heavy failures by class: blocked=1 (Table 3).

**5. Did schema discovery (the JS litmus) produce usable contracts?**
quotes-js-rendered: compile ok, 1 ok run(s); quotes-scroll: compile ok, 1 ok run(s).

**6. What does HTTP amortization save vs 20 counterfactual agent runs?**
Measured: 20 HTTP runs took 16722 ms total at $0.0000; 20 agent runs would take ~1601695 ms at measured mean agent cost (Table 4).

**7. Does the system stay correct under concurrency and within budget?**
W4: 20/20 ok, 0 5xx/DB errors. Budget: 20/22 agent ops, $1.2415/$2.00 spent; no ops skipped.

## Parallelism note

H agent sessions were capped at K=2 concurrent (`--h-concurrency`), in line with H's multi-agent guidance: https://hub.hcompany.ai/computer-use-agents/multi-agent. Discovery compiles share the same semaphore since they consume a session in live mode.

## Erratum (post-run correction)

G3's FAIL is a labeling artifact, not a router failure: all 5 "TRAP" runs were the
eval's own deliberate `force_path=agent` probes (one per http-graduated contract, run
to measure the agent counterfactual). Zero spontaneous http→agent fallthroughs
occurred — every default-path run on an http-expected task served with `path=http`
(80/80). The script now excludes forced probes from TRAP labeling; with that fix G3 is
a PASS on this dataset. Similarly, the "mean cost" column for http tasks averages in
the one forced agent probe — the http-path runs themselves all cost $0.00.
