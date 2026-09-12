# Harbour SLOs

These numbers are what we page on for the packaged HTTP service. They are not
the held-out task-success bar (that is a qualification target, not this file).

## Latency

- **p95** of successful sequential `POST /run` (synthetic checker inputs,
  pass-through, local process) is **1500 ms** on the hardware used for OP-01
  contract runs.
- Measured on 2026-09-12: checker report `results/raw/after-openai-full.json`
  recorded **p95 1223 ms** (20 samples). That run is under the objective.
- Packaging overhead vs the shipped agent must stay **≤ 1.5×** on the same
  machine and cases (qualification). We do not have a private 60-case p95 in
  this repo; do not treat 1223 ms as that number.
- Upstream call timeout is 8 s; a hung provider becomes `504` rather than an
  unbounded wait. p95 is for *successful* 200s, not for injected faults.

## Availability

- **99%** of `GET /healthz` and `GET /readyz` probes against a correctly
  configured process return 200 while the process is up.
- `/readyz` is allowed to be 503 when `MAX_SPEND_USD` is unparseable or the DB
  will not open — that is fail-closed, not an SLO breach of the *configured*
  service.
- **99%** of `POST /run` with a valid body, under the spend cap, and with a
  healthy gateway, complete with HTTP 200 or a mapped upstream envelope
  (`502` / `503` / `504`). Transport timeouts on the client after 8 s of
  upstream stall are counted as our error, not the provider's.

## Eval gate

- Clean `make eval` (checker env, `LLM_BASE_URL` set): report `pass: true`,
  `cases >= 50`, exit 0. Current threshold is **90%** (`0.9` in
  `eval/suite.py`).
- Under gateway regressions R1–R4: `pass: false` and non-zero exit. A green
  eval during a prompt regression is an SLO miss for the deploy gate, even if
  HTTP is up.

## Error budget (how we act)

- If p95 on the next full checker latency block exceeds 1500 ms, stop feature
  work and inspect `harbour/llm.py` retries and `/run` OTLP export.
- If `/readyz` flaps on a good config, inspect `HARBOUR_DB` locks and cap parse.
- Spend: process cap is the hard stop. Burning the cap is an incident, not an
  SLO “slow day”.

## What this file does not cover

Held-out `goal_state` match rate, private detector findings, and token spend
≤ 3× median are qualification bars. They are tracked in `EXPERIMENT_LOG.md`
and `results/`, not as HTTP SLOs.
