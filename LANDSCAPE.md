# Landscape

OP-01 is “ship the inherited agent,” not “replace it with a framework.” I looked at what already exists and what we actually used.

**Kept from the inheritance.** Stdlib `http.server` (no FastAPI in Harbour itself). SQLite tool layer as the only writer of `audit_log`. JSON-one-action loop instead of provider tool-calling , the starter comments said that path was more stable across snapshots. `policy.md` / `policy.py` as the written limits; we did not rewrite policy to make gold easier.

**Contract / observability.** OpenTelemetry GenAI-style spans and OTLP/HTTP JSON, because item 3 names that pipe. We did not add a vendor APM. Cost uses `contract_check/prices.yaml` (exact id, then prefix) so our `cost_usd` matches the gateway within the allowed slack.

**Models.** Season pin `gpt-4.1-mini-2025-04-14`. Official `prices.yaml` only lists the two dated snapshots. We did not patch their price table. All checker runs used OpenAI as `--upstream` so spend could be priced.

**Eval.** The starter 40-case fake suite is the thing the brief calls thin on purpose. LangSmith / promptfoo would help a product team later; they would not have satisfied item 9 without `make eval` + R1–R4 at this gateway. I did not pull in an extra eval product for the exam.

**Agent frameworks (LangGraph, Crew, etc.).** Rejected for this SHA. Swapping the loop would be a large diff to justify under “everything behind `/case` is yours,” and it would not by itself fix sticky verify or overlay tool args. If we were carrying a library to the next engagement, a thin policy-gate around tools would be the portable piece, not a graph runtime.

**HTTP client.** Harbour `llm.py` stays urllib. The checker uses httpx; that is their harness, not ours.

**What I did not use.** Fine-tunes, RAG, a second model as critic, Docker-only deploy. None of those are required for the ten items, and they would eat the US$50 results ceiling.
