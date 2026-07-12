# API H — hard eval report

Generated 2026-07-12T02:08:37+00:00 · base_url `http://127.0.0.1:8000` · h_mode `live` · K=2 · agent ops 20/20 · cost $0.3643/$2.00

## Table 1 — per-task results

| task_id | js | expected | diff | compile | runs ok/total | paths | latency p50/p95 ms | mean cost | error classes |
|---|---|---|---|---|---|---|---|---|---|
| hn-top-baseline | api | http | 1 | ok | 41/41 | {'http': 40, 'agent': 1} | 513 / 932 | $0.0153 | — |
| hn-ask-show | api | http | 2 | ok | 21/21 | {'http': 20, 'agent': 1} | 243 / 1818 | $0.0131 | — |
| wikipedia-toc | static | agent | 2 | ok | 1/1 | {'agent': 1} | 67350 / 67350 | $0.0620 | — |
| github-repo-meta | spa | agent | 3 | ok | 0/1 | — | 7 / 7 | — | {'other': 1} |
| craigslist-sf-bikes | softbot | agent | 4 | ok | 1/1 | {'agent': 1} | 208492 / 208492 | $0.0886 | — |
| hn-algolia-ui | csr | agent | 3 | ok | 0/2 | — | 232 / 4 | — | {'schema': 1, 'other': 1} |
| quotes-js-rendered | csr | agent | 3 | ok | 1/1 | {'agent': 1} | 28019 / 28019 | $0.0119 | — |
| quotes-scroll | scroll | agent | 4 | ok | 1/1 | {'agent': 1} | 111023 / 111023 | $0.0306 | — |
| weather-wttr | api | http | 1 | ok | 11/11 | {'http': 10, 'agent': 1} | 170 / 749 | $0.0237 | — |
| openlibrary-search | api | http | 2 | ok | 5/6 | {'http': 5} | 134 / 218 | — | {'other': 1} |
| books-toscrape | static | agent | 2 | ok | 1/1 | {'agent': 1} | 38121 / 38121 | $0.0135 | — |
| demoqa-dynamic | dynamic | agent | 4 | ok | 1/1 | {'agent': 1} | 35335 / 35335 | $0.0231 | — |
| spa-nav | spa | agent | 4 | ok | 1/1 | {'agent': 1} | 29877 / 29877 | $0.0170 | — |
| cookie-consent-content | consent | agent | 4 | ok | 1/1 | {'agent': 1} | 66701 / 66701 | $0.0392 | — |
| github-issues-spa | spa | agent | 4 | ok | 1/1 | {'agent': 1} | 68926 / 68926 | $0.0264 | — |
| hn-item-thread | static | agent | 3 | ok | 0/1 | — | 195626 / 195626 | — | {'empty': 1} |
| multi-step-js-chain | csr | agent | 5 | ok | 0/0 | — | — | — | — |
| softwall-probe | softbot | agent | 5 | ok | 0/0 | — | — | — | — |
| graphql-countries | graphql | http | 1 | ok | 5/6 | {'http': 5} | 163 / 446 | — | {'other': 1} |

## Table 2 — cohorts

Cohorts: `http_api` (expected http), `agent_js_heavy` (csr|spa|scroll|consent|dynamic|softbot), `agent_other` (remaining agent tasks).

| cohort | tasks | runs | ok | success rate | latency p50/p95 ms | mean cost |
|---|---|---|---|---|---|---|
| http_api | 5 | 85 | 83 | 98% | 254 / 1818 | $0.0174 |
| agent_js_heavy | 11 | 10 | 7 | 70% | 32606 / 111023 | $0.0338 |
| agent_other | 3 | 3 | 2 | 67% | 67350 / 67350 | $0.0377 |

## Table 3 — JS failure taxonomy (failed runs by error_class × js_profile)

| error_class | api | consent | csr | dynamic | graphql | scroll | softbot | spa | static | total |
|---|---|---|---|---|---|---|---|---|---|---|
| schema | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| empty | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| blocked | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| timeout | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| hydration | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| other | 1 | 0 | 1 | 0 | 1 | 0 | 0 | 1 | 0 | 4 |

## Table 4 — amortization (20× HN HTTP measured vs counterfactual agent)

| variant | runs | total latency ms | total cost |
|---|---|---|---|
| measured: 20× HN via HTTP (W4 burst) | 20 (20 ok) | 14752 | $0.0000 |
| counterfactual: 20× agent (measured means: 68162 ms, $0.0304/run) | 20 | 1363243 | 0.6071 |

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
| G8 | budget respected (agent ops ≤ 20, cost ≤ $2.00) | PASS |
| G9 | record integrity: every ok run has a path; every failed run is classified | PASS |

## Narrative

**1. Which tasks graduate to pure HTTP, and does the HTTP path avoid H sessions?**
Tasks served over HTTP: graphql-countries, hn-ask-show, hn-top-baseline, openlibrary-search, weather-wttr. 80/80 http-path runs completed with no H session attached — the contract, not the agent, does the work.

**2. Does the router honor expected paths (any TRAP events)?**
3 TRAP run(s) — http-expected tasks that fell through to the agent path.

**3. How do JS-heavy profiles fare on the agent path vs other agent tasks?**
agent_js_heavy success 70% vs agent_other 67% (Table 2).

**4. What failure classes dominate on JS-heavy tasks?**
JS-heavy failures by class: other=2, schema=1 (Table 3).

**5. Did schema discovery (the JS litmus) produce usable contracts?**
quotes-js-rendered: compile ok, 1 ok run(s); quotes-scroll: compile ok, 1 ok run(s).

**6. What does HTTP amortization save vs 20 counterfactual agent runs?**
Measured: 20 HTTP runs took 14752 ms total at $0.0000; 20 agent runs would take ~1363243 ms at measured mean agent cost (Table 4).

**7. Does the system stay correct under concurrency and within budget?**
W4: 20/20 ok, 0 5xx/DB errors. Budget: 20/20 agent ops, $0.3643/$2.00 spent; 3 op(s) skipped when the budget guard tripped: EXTRA:hn-item-thread:force-agent, EXTRA:multi-step-js-chain:run 1/1, EXTRA:softwall-probe:run 1/1

## Parallelism note

H agent sessions were capped at K=2 concurrent (`--h-concurrency`), in line with H's multi-agent guidance: https://hub.hcompany.ai/computer-use-agents/multi-agent. Discovery compiles share the same semaphore since they consume a session in live mode.

## Budget note

Budget guard stopped launching new agent ops after 20 op(s) / $0.3643. Skipped: EXTRA:hn-item-thread:force-agent, EXTRA:multi-step-js-chain:run 1/1, EXTRA:softwall-probe:run 1/1
