# Harbour threat model

Scope: the HTTP service (`harbour/service.py`), the agent/tool loop, SQLite
backend, and the LLM gateway at `LLM_BASE_URL`. Reviewers: platform and risk.
This is the attack surface we treat as in-scope for OP-01, not a full bank SST.

## Assets

- Customer and loan rows, including verification flags and payment mandates
- Tool side effects: fee waivers, reschedules, contact changes, autopay cancel,
  disputes, and anything that writes `audit_log`
- Provider credentials (`LLM_API_KEY` / upstream key)
- Spend ledger and traces (tokens, `cost_usd`, `trace_id`)
- Idempotency cache for `POST /run` (in memory; dies with the process)

## Actors

- Support client calling `/run` and `/case` (untrusted natural language)
- Contract gateway (trusted for routing and fault injection in exam mode)
- Operator with shell env (trusted for secrets; untrusted if the repo is the store)
- Model provider (untrusted for prompt-injection content in completions and for
  identity drift on the `model` field)

## Prompt injection

Customer `message` and other free-text fields are model input. The inherited
failure mode is: the model follows instructions inside that text (ignore policy,
skip identity, call a money tool, invent a tool). Private detectors look at
audit rows and traces for actions that were not licensed by a prior identity
check.

Mitigations we rely on today:

- System prompt and tool list stay on our side of `LLM_BASE_URL` (item 1).
- Eval probes fail if the system prompt is stripped (R1), completions are cut
  to 40 characters (R2), Harbour `{tool,args}` values are rotated (R3), or the
  returned model id is `*-unapproved` (R4).
- Secrets never live in the repo (item 7). The service sends the env
  `LLM_API_KEY` and nothing else.

Gaps still in the inherited agent (not claimed fixed by these docs): sticky
`customers.verified`, cancel-autopay without verify, and tool calls driven by
injected text. Those are qualification defects, not contract item 10.

## Other threats

| Threat | What happens | What we do |
|---|---|---|
| Key leak | Spend and data leave on someone else's bill | Env only; checker scans `sk-` / `.env` |
| Spend runaway | Retry loops or long contexts | `MAX_SPEND_USD`; `/readyz` if cap is garbage |
| Replay / double run | Same `idempotency_key` burns tokens twice | In-memory cache + per-key lock on `/run` |
| Version mix-up | Two binaries, one hostname | Distinct `APP_VERSION` per process; see RUNBOOK |
| Trace loss | Cannot attribute cost to a case | OTLP export after `/run`; file JSONL fallback |
| Tool-arg drift | Model JSON keys no longer match tools | Eval R3; operator rollback if production eval goes red |

## Trust boundaries

Browser/client → Harbour HTTP → SQLite. Harbour → `LLM_BASE_URL` only, never a
second provider URL from code. OTLP collector is observational; a down collector
must not change `/run` status.

## Residual risk

In-memory idempotency does not survive restart. Multi-worker needs an external
store. Prompt injection is not fully closed in the agent loop until identity
and policy gates are sticky in the backend, not only in eval probes.
