# Decisions

Coding-agent : I used Cursor (Grok) to implement HTTP/eval/OTEL pieces and to draft this package. I ran the contract checker, the live `goal_scorer.py` sample, and `pytest harbour/tests` myself. I did not accept a prompt tweak that made the 8-case live sample worse (5/8 vs 7/8). I did not edit `cases/cases.jsonl`, `goal_scorer.py`, or `contract_check/`.

---

## 1. Timeout: fail the call vs retry forever

**Hypothesis.** The ReadTimeouts on `slow10x` / `tool_timeout` were “we need a longer client timeout.”

**Options.** (A) Keep the inherited 60 s timeout and hope the checker waits. (B) Bound the call (we used 8 s) and map timeout to `504` **without** retrying that attempt. (C) Retry timeouts with backoff.

**Constraint.** Item 5 requires a mapped envelope and bounded retries; a hung `/run` also blows p95. Retrying a timeout can double-apply a tool if the upstream actually committed.

**Observation.** Full checker with 60 s: item 5 fail, ReadTimeout on those scenarios (`EXPERIMENT_LOG.md` afternoon / later; `results/raw/after-openai-full.json` at the 4/10 then 5/10 overwrite). After 8 s + no retry on timeout: `--only 5` pass, 100% scenarios (`results/raw/after-faults.json`).

**Chosen.** (B).

**Reverse if.** A measured pass-through p95 on real cases needs a longer timeout *and* we have an idempotent tool story; not because 8 s “looks unique.”

---



## 2. Item 9 eval: probes through the gateway vs only published cases

**Hypothesis.** Forty easy published cases plus `LLM_FAKE=1` would satisfy `make eval`.

**Options.** (A) Leave the starter suite; add a Makefile that writes `eval/eval_report.json`. (B) Fifty gateway probes that assert phrase / length / `{tool,args}` / model id, report at repo root. (C) Run all 180 cases live in `make eval` (cost, slow, still might miss R3 if we never parse Harbour JSON).

**Constraint.** Item 9: `cases >= 50`, root `eval_report.json`, traffic via `LLM_BASE_URL`, **fail** under R1–R4. The starter sample is 40 and fake by default.

**Observation.** First item 9: no Makefile / no root report. After Makefile + 50 probes: R1, R2, R4 detected; **R3 not detected** because the probe was two lines (phrase + JSON) and the gateway only scrambles a whole-message `{tool,args}` object (`results/raw/after-eval.json`). One-object probe: all four detected (`results/raw/after-eval-r3.json`). This is a **failure** we kept in the log; we did not hide it.

**Chosen.** (B) for the contract gate. Published `goal_state` stays a separate check with unmodified `goal_scorer.py`, not a replacement for R1–R4.

**Reverse if.** Probes pass item 9 but private detectors still show a thin eval; then fold real `/case` rows into `make eval` without dropping the four assertions.

---



## 3. Identity: DB flag vs this-case verify (and a failed prompt patch)

**Hypothesis.** `customers.verified` in SQLite was the identity gate.

**Options.** (A) Leave it — seed already marks some people verified. (B) Require a successful `verify_identity` on **this** `case_id` in the audit log, including `cancel_autopay`. (C) Reset the flag at process start only.

**Constraint.** Policy: verification is this contact. Detectors look at audit order, not our pytest. Sticky flag lets money tools skip verify.

**Observation.** Offline tests passed after (B) (`harbour/tests/test_backend.py`). Live `goal_scorer` sample 7/8 then 6/8 (`EXPERIMENT_LOG.md` night). Adding more prompt text to “always send the statement” dropped the sample to 5/8; we **reverted** that. Overlay still blocked in code (`_guard_untrusted`) so extra waive/phone from a paste should not land in audit.

**Chosen.** (B), plus a code guard, not a longer system prompt.

**Reverse if.** Held-out identity cases fail because we require verify when gold expects a pre-verified skip - then we would be wrong about “this contact.” Evidence would be `goal_scorer` on those cases, not a vibe.

---



## Failure we are not papering over

Item 9 first R3 miss; `--report` reuse that destroyed the 4/10 JSON; the 9/10 full run where item 4 said spend could not be verified after ~250 eval calls, then `--only 4` passed (`after-cap-retry.json`) and a second full run was 10/10. Also: live injection cases that escalate instead of `send_statement`. 13 September live `goal_scorer` on all 180 published cases: 121/180 (`EXPERIMENT_LOG.md`). I am not adding per-case prompt rules for the 59 misses (third waiver, already-waived fee, debt-advice escalate, cannot-move-EMI). That would overfit the public file. Those stay in the log.

Item 3 passed on synthetic `/run` with chat spans only. `record_tool_call` was unused until 13 Sep evening; we wired it in `_call_tool` so `/case` traces include `execute_tool` (see experiment log). That is not a fourth scored decision — it closes a gap in the brief’s tracing ask.
