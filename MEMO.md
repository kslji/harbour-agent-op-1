# Memo — Harbour, as inherited vs as shipped

To: Head of platform engineering  
From: Harbour OP-01 hardening  
Date: 13 September 2026

We inherited a demo that closed easy servicing cases and a green eval that did not notice when behaviour changed. Platform would not put it behind the load balancer. This note is what I would tell a director in one sitting.

**What was actually wrong.** Six complaints, not six unrelated bugs. (1) There was no `/readyz` and `/healthz` was a toy `{"ok":true}`, so nothing could load-balance it. (2) Model calls had no hard timeout, so a slow upstream hung the checker and would hang a worker. (3) Spend was not capped in-process and not attributed on traces. (4) `POST /run` replayed work when the same idempotency key came twice. (5) The eval suite was 40 offline cases that stayed green if the system prompt vanished or tool JSON was scrambled. (6) Money tools trusted a sticky `customers.verified` flag from an earlier contact, and `cancel_autopay` did not require verify at all — which matches the audit row where money moved with no identity step. Pasted “SYSTEM:” / override text in the customer message could also become extra tool calls; the inherited loop even replayed free-text notes back as user turns.

**What it now guarantees.** Contract checker at `results/contract_check.json`: 10/10, faults 100%, p95 902 ms on synthetic `/run`. Every model call still goes through `LLM_BASE_URL`. `/healthz` reports `APP_VERSION`; `/readyz` fails closed on a garbage spend cap. Chat timeout is 8 s; 504 on timeout without retrying that call. Cap is `MAX_SPEND_USD`. Same idempotency key plus same input replays; different input is 409. Traces go to OTLP with tokens and `cost_usd`. `make eval` writes root `eval_report.json` and goes red under the four published prompt regressions. Money tools, including cancel-autopay, require a successful `verify_identity` **on this case**, not a leftover DB flag. Overlay-only contact changes and extra waives are refused before they hit the audit log.

**What it still does not.** We have not scored the 60 held-out cases; do not treat 10/10 HTTP as task-success. On published injection samples a live model sometimes **escalates** a statement request instead of sending the statement (c_0168, sometimes c_0166). That is safer than following the paste, and worse than doing the in-policy ask. Idempotency is in-memory and dies on restart. Prompt injection is not “solved”; it is constrained in the tool layer.

**How you would know within an hour.** `/readyz` 503, a burst of 504s, spend cap hits, `make eval` green while you know a prompt changed, or OTLP missing after `/run`. Turn it off: stop the process (see RUNBOOK rollback). Two versions can run on different `PORT` / `APP_VERSION` without a rebuild.

**Who pays residual risk.** If we ship with the escalate-instead-of-statement behaviour, customers wait on a human for a statement; ops pays. If we loosen the overlay guard, risk pays when a pasted note moves money. Pause rollout if eval does not fail under the four gateway regressions, if `/readyz` flaps on good config, or if audit shows a money tool without `verify_identity` on that case.

**Cost of one resolved case.** A tiny synthetic `/run` in the checker is about **$0.00002** on `gpt-4.1-mini-2025-04-14`. A real servicing case is several `complete()` calls; I would budget **well under a cent** on that snapshot unless a retry loop starts. We do not have a 180-case median in this repo. The spend cap is the hard stop, not an SLO.
