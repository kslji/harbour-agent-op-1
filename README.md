# Harbour Agent: OP-01 solution

This is my OP-01 solution: Harbour as I inherited it, then made it something platform could put behind a load balancer. `POST /case` is unchanged. This repo is the private solution, not a copy of the public `references/OP-01` folder.

**Do not commit API keys.** Export them in the shell.

## Run

Python 3.11 (Apple’s 3.9 breaks `datetime.UTC` in the checker).

```bash
export LLM_BASE_URL=https://api.openai.com/v1   # or the contract gateway
export LLM_API_KEY=...                          # gateway token in exam mode
export LLM_MODEL=gpt-4.1-mini-2025-04-14
export APP_VERSION=1.0.0
export PORT=8000
export MAX_SPEND_USD=5
# optional: OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:8602

./scripts/reproduce.sh start
# or: /opt/homebrew/bin/python3.11 -m harbour.service
```

`LLM_FAKE=1` is canned replies only (offline tests). Unset it for real model traffic.

```bash
./scripts/reproduce.sh eval     # make eval → eval_report.json at repo root
./scripts/reproduce.sh help     # how to invoke the contract checker
```



## What changed (short)

HTTP: `/healthz`, `/readyz`, `POST /run` (idempotency, spend, OTEL). LLM: 8 s timeout, mapped 502/503/504. Eval: `make eval`, 50 probes when `LLM_BASE_URL` is set. Agent/backend: verify this case before money tools including `cancel_autopay`; refuse overlay-only extra tools before audit.

Unmodified on purpose: `cases/cases.jsonl`, `goal_scorer.py`, `contract_check/`.

## Evidence

- `results/contract_check.json` — 10/10 (13 Sep 2026)
- `results/raw/` — earlier fails and `--only` runs
- `EXPERIMENT_LOG.md`, `DECISIONS.md`, `MEMO.md`, `RUNBOOK.md`, `THREAT_MODEL.md`, `SLO.md`

Held-out match rate is not claimed here.
