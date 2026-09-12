"""Span emission for Harbour.

Spans are written one-per-line as JSON to ``$HARBOUR_TRACE_FILE`` (default
``traces/otlp.jsonl``) in a flattened OpenTelemetry GenAI shape:

    {"trace_id", "span_id", "parent_span_id", "name", "start_ms", "end_ms",
     "attributes": {...}}

The file is append-only. When ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set, ``export_otlp``
POSTs the same spans to ``<endpoint>/v1/traces`` as OTLP/JSON.
"""

from __future__ import annotations

import contextvars
import json
import os
import re
import threading
import time
import uuid
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

DEFAULT_TRACE_FILE = "traces/otlp.jsonl"
_PRICES_PATH = Path(__file__).resolve().parent.parent / "contract_check" / "prices.yaml"
_DEFAULT_PRICES = {
    "gpt-4.1-mini-2025-04-14": (0.40, 1.60),
    "gpt-5-mini-2025-08-07": (0.25, 2.00),
}

_write_lock = threading.Lock()
_pending: dict[str, list[dict[str, Any]]] = {}

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "harbour_trace_id", default=None
)
_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "harbour_span_id", default=None
)
_case_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "harbour_case_id", default=""
)

def _load_prices() -> dict[str, tuple[float, float]]:
    path = Path(os.environ["PRICES"]) if os.environ.get("PRICES") else _PRICES_PATH
    if not path.is_file():
        return dict(_DEFAULT_PRICES)
    prices = dict(_DEFAULT_PRICES)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        match = re.match(
            r"^([A-Za-z0-9._-]+):\s*\{input:\s*([0-9.]+),\s*output:\s*([0-9.]+)\}",
            line,
        )
        if match:
            prices[match.group(1)] = (float(match.group(2)), float(match.group(3)))
    return prices


def cost_usd_for(model: str, input_tokens: int, output_tokens: int) -> float:
    """USD for one call at contract_check/prices.yaml rates (exact id, then prefix)."""
    prices = _load_prices()
    rates = prices.get(model)
    if rates is None:
        prefix = ""
        for name, pair in prices.items():
            if model.startswith(name) and len(name) >= len(prefix):
                prefix, rates = name, pair
    if rates is None:
        return 0.0
    return input_tokens * rates[0] / 1e6 + output_tokens * rates[1] / 1e6


def trace_file() -> Path:
    """Absolute path of the JSONL trace sink for this process."""
    return Path(os.environ.get("HARBOUR_TRACE_FILE", DEFAULT_TRACE_FILE)).resolve()


def _new_id(width: int) -> str:
    return uuid.uuid4().hex[:width]


def _price(model: str, input_tokens: int, output_tokens: int) -> float:
    return round(cost_usd_for(model, input_tokens, output_tokens), 6)


def current_trace_id() -> str:
    """Trace id for the calling context, minting one if the context is fresh."""
    tid = _trace_id.get()
    if tid is None:
        tid = _new_id(32)
        _trace_id.set(tid)
    return tid


def set_case_id(case_id: str) -> None:
    """Tag every span emitted from this context with a case id."""
    _case_id.set(case_id)


def current_case_id() -> str:
    return _case_id.get()


def new_trace(trace_id: str | None = None) -> str:
    """Begin a new trace and return its id. Called once per case."""
    tid = trace_id or _new_id(32)
    _trace_id.set(tid)
    _span_id.set(None)
    return tid


def _emit(record: dict[str, Any]) -> None:
    path = trace_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, default=str, separators=(",", ":"))
    with _write_lock:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _pending.setdefault(str(record.get("trace_id") or ""), []).append(record)


def _otlp_kv(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        packed: dict[str, Any] = {"boolValue": value}
    elif isinstance(value, int):
        packed = {"intValue": str(value)}
    elif isinstance(value, float):
        packed = {"doubleValue": value}
    else:
        packed = {"stringValue": str(value)}
    return {"key": key, "value": packed}


def export_otlp(trace_id: str) -> None:
    """POST this request's spans to OTEL_EXPORTER_OTLP_ENDPOINT/v1/traces (JSON)."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if not endpoint or not trace_id:
        return
    with _write_lock:
        records = list(_pending.get(trace_id, []))
    if not records:
        return
    spans = []
    for record in records:
        attrs = [
            _otlp_kv(key, value)
            for key, value in (record.get("attributes") or {}).items()
            if value is not None
        ]
        start_ms = int(record.get("start_ms") or 0)
        end_ms = int(record.get("end_ms") or start_ms)
        spans.append(
            {
                "traceId": record["trace_id"],
                "spanId": record["span_id"],
                "parentSpanId": record.get("parent_span_id") or "",
                "name": record.get("name") or "",
                "kind": 1,
                "startTimeUnixNano": str(start_ms * 1_000_000),
                "endTimeUnixNano": str(end_ms * 1_000_000),
                "attributes": attrs,
                "status": {"code": 1},
            }
        )
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [_otlp_kv("service.name", "harbour")]},
                "scopeSpans": [{"scope": {"name": "harbour"}, "spans": spans}],
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        endpoint + "/v1/traces",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            response.read()
    except (urllib.error.URLError, TimeoutError, OSError):
        pass


class Span:
    """A span in flight. Attributes may be added until the block exits."""

    def __init__(self, name: str, attributes: dict[str, Any]) -> None:
        self.name = name
        self.attributes = dict(attributes)
        self.trace_id = current_trace_id()
        self.span_id = _new_id(16)
        self.parent_span_id = _span_id.get()
        self.start_ms = int(time.time() * 1000)
        self.end_ms: int | None = None

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def update(self, **attrs: Any) -> None:
        self.attributes.update(attrs)

    def to_record(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms if self.end_ms is not None else self.start_ms,
            "attributes": self.attributes,
        }


@contextmanager
def start_span(name: str, **attrs: Any) -> Iterator[Span]:
    """Open a span, yield it so callers can attach attributes, then emit it."""
    span = Span(name, attrs)
    token = _span_id.set(span.span_id)
    try:
        yield span
    except Exception as exc:  # noqa: BLE001 - recorded then re-raised
        span.set_attribute("error.type", type(exc).__name__)
        raise
    finally:
        _span_id.reset(token)
        span.end_ms = int(time.time() * 1000)
        _emit(span.to_record())


def record_tool_call(
    tool: str,
    case_id: str,
    *,
    ok: bool,
    duration_ms: int,
    error: str | None = None,
) -> None:
    """Emit a span describing one backend tool invocation."""
    record = {
        "trace_id": current_trace_id(),
        "span_id": _new_id(16),
        "parent_span_id": _span_id.get(),
        "name": f"tool {tool}",
        "start_ms": int(time.time() * 1000) - duration_ms,
        "end_ms": int(time.time() * 1000),
        "attributes": {
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool,
            "harbour.case_id": case_id,
            "harbour.ok": ok,
            "error.type": error,
        },
    }
    _emit(record)
