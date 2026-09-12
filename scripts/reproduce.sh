#!/bin/sh
# OP-01: subcommands so `reproduce.sh` does not exec a server and block eval.
set -eu
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python3}"
cmd="${1:-help}"

case "$cmd" in
  start)
    exec "$PYTHON" -m harbour.service
    ;;
  eval)
    exec make eval
    ;;
  check)
    cat <<'EOF'
Contract checker (you must export UPSTREAM_API_KEY; do not put keys in this repo).
Do not start Harbour yourself when using --start-cmd.

  unset LLM_FAKE
  export LLM_MODEL=gpt-4.1-mini-2025-04-14
  python3.11 -m contract_check.check \
    --target http://127.0.0.1:8000 \
    --upstream https://api.openai.com/v1 \
    --repo . \
    --start-cmd "python3.11 -m harbour.service" \
    --app-version 1.0.0 \
    --report results/contract_check.json
EOF
    ;;
  help|*)
    cat <<'EOF'
reproduce.sh — Harbour OP-01

  ./scripts/reproduce.sh start   # HTTP service (honours PORT, LLM_*, MAX_SPEND_USD)
  ./scripts/reproduce.sh eval    # make eval; writes ./eval_report.json
  ./scripts/reproduce.sh check   # print checker command; does not start a server
  ./scripts/reproduce.sh help

Use PYTHON=/path/to/python3.11 if `python3` is 3.9.
Offline unit tests: PYTHON=python3.11 python3.11 -m pytest harbour/tests -q
EOF
    ;;
esac
