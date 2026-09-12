# OP-01: `make eval` must write eval_report.json at the repository root.
PYTHON ?= python3

.PHONY: eval
eval:
	$(PYTHON) eval/suite.py --report eval_report.json
