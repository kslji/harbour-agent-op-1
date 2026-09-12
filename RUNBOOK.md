# Harbour runbook

Loan-servicing agent HTTP surface. Start from the repository root. Python 3.11.
Do not put API keys in files; export them in the shell.

## Start

```
export LLM_BASE_URL=...          # contract gateway or provider /v1
export LLM_API_KEY=...           # gateway token, not committed
export LLM_MODEL=gpt-4.1-mini-2025-04-14
export APP_VERSION=1.0.0
export PORT=8000
export MAX_SPEND_USD=5
export OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:8602
/opt/homebrew/bin/python3.11 -m harbour.service
```

`PORT` wins over `HARBOUR_PORT`. Default listen is 8080 if neither is set.
`HARBOUR_DB` is the SQLite path (default `harbour.db`). Seed loads only if
the customers table is empty. Two processes must not share one DB file if
they both write cases.

## Health

- `GET /healthz` → `{"status":"ok","version":"<APP_VERSION>"}`
- `GET /readyz` → 200 when the DB opens and `MAX_SPEND_USD` parses; 503 otherwise
- `POST /run` and `POST /case` are the work endpoints
- Unset `LLM_FAKE` for real model traffic; `LLM_FAKE=1` is canned replies only

## Two versions at once

The same package runs twice. Traffic switch is configuration (`PORT`,
`APP_VERSION`), not a rebuild.

1. Instance A: `APP_VERSION=1.0.0 PORT=8000` (or whatever A already uses).
2. Instance B: `APP_VERSION=1.0.0-b PORT=<free port>` and a distinct `HARBOUR_DB`.
3. Confirm each `/healthz` reports its own version and both answer `POST /run`.
4. Point the load balancer (or checker `--target` / `--target-b`) at A or B.
5. Stop B when A is enough. A must keep answering `/run`.

The contract checker does this itself when you pass `--start-cmd`.

## Rollback

Target: under five minutes. No image rebuild.

1. Keep instance A running. Do not kill A to “make room” for B.
2. Stop sending traffic to B (checker: it stops the B process).
3. Confirm A `/healthz` still matches the previous `APP_VERSION` and `POST /run` returns 200.
4. If A is the bad one: start the last known-good command line with the old
   `APP_VERSION` on a free port, switch traffic, then stop the bad listener.
5. If spend is the incident: stop the process. Cap is in-process; a restart
   resets the counter. Fix `MAX_SPEND_USD` before bringing it back.

Wall clock for a local two-process swap is a start plus two health checks,
not a deploy pipeline.

## Faults and spend

Upstream 429 maps to `503 upstream_rate_limited` (honours Retry-After).
5xx maps to `502 upstream_error`. Call timeout (8s) maps to `504 upstream_timeout`
with no retry on that path. Chat timeout and attempt caps live in `harbour/llm.py`.
`MAX_SPEND_USD` that does not parse → `/readyz` not ready. Hitting the cap
rejects further `/run` work.

Traces: JSONL at `HARBOUR_TRACE_FILE` plus OTLP/JSON POST to
`$OTEL_EXPORTER_OTLP_ENDPOINT/v1/traces`. Export failure must not fail `/run`.

## Eval

`make eval` from the repo root writes `eval_report.json` there. The checker
runs it with `LLM_BASE_URL` set. Offline `LLM_FAKE=1` is the inherited
forty-case sample and is not the contract item 9 path.

## Stop

Ctrl-C the process, or kill the PID bound to `PORT`. Check `lsof -iTCP:$PORT -sTCP:LISTEN`
so a leftover Harbour is not answering the next checker start.
