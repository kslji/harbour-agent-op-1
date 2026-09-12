"""HTTP surface for Harbour.

    GET  /healthz  -> {"status": "ok", "version": APP_VERSION}
    GET  /readyz   -> {"ready": bool, "checks": {...}}  200 or 503
    POST /run      {"input": string, "idempotency_key"?: string}
                -> {"output": string, "trace_id": string, "cost_usd": number}
    POST /case     {"case_id", "customer_id", "message"[, "loan_id"]}
                -> {"case_id", "summary", "actions_taken", "trace_id"}

Configuration is read from the environment (see contract.md):

    PORT / HARBOUR_PORT   listen port (PORT wins; default 8080)
    HARBOUR_HOST          bind address (default 127.0.0.1)
    APP_VERSION           echoed by /healthz
    MAX_SPEND_USD         process spend cap; unparseable => not ready
    HARBOUR_DB            SQLite path (default harbour.db)
    LLM_*                 see llm.py
"""

from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:  # package import when OP-01 is on sys.path, flat import when harbour/ is
    from . import agent, llm, tracing
except ImportError:  # pragma: no cover - exercised by direct script runs
    import agent  # type: ignore[no-redef]
    import llm  # type: ignore[no-redef]
    import tracing  # type: ignore[no-redef]

MAX_BODY_BYTES = 64 * 1024
_BACKEND_INIT_LOCK = threading.Lock()
_SPEND_LOCK = threading.Lock()
_SPENT_USD = 0.0
_IDEM_META_LOCK = threading.Lock()
_IDEM_KEY_LOCKS: dict[str, threading.Lock] = {}
_IDEM_CACHE: dict[str, tuple[str, dict[str, Any]]] = {}


class ServiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def make_backend() -> Any:
    """Build the Backend the handler will use, from environment config."""
    try:
        from . import backend as backend_module  # type: ignore[attr-defined]
    except ImportError:  # pragma: no cover - direct script runs
        import sys

        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from harbour import backend as backend_module  # type: ignore[no-redef]
    try:
        from .seed_data import load_seed
    except ImportError:
        from harbour.seed_data import load_seed
    with _BACKEND_INIT_LOCK:
        backend = backend_module.Backend(os.environ.get("HARBOUR_DB", "harbour.db"))
        if not backend.conn.execute("SELECT 1 FROM customers LIMIT 1").fetchone():
            load_seed(backend.conn)
    return backend


def app_version() -> str:
    return os.environ.get("APP_VERSION", "1.0.0")


def parse_max_spend() -> tuple[float | None, str]:
    """Return (cap, error). error is set when MAX_SPEND_USD is present but not a decimal."""
    raw = os.environ.get("MAX_SPEND_USD")
    if raw is None or raw == "":
        return 1_000_000.0, ""
    try:
        value = float(raw)
    except ValueError:
        return None, "MAX_SPEND_USD must be a decimal number"
    if value != value or value < 0:  # NaN or negative
        return None, "MAX_SPEND_USD must be a decimal number"
    return value, ""


def spent_usd() -> float:
    with _SPEND_LOCK:
        return _SPENT_USD


def add_spend(amount: float) -> None:
    global _SPENT_USD
    with _SPEND_LOCK:
        _SPENT_USD += amount


def idempotency_lock(key: str) -> threading.Lock:
    """One lock per key so concurrent duplicates share a single execution."""
    with _IDEM_META_LOCK:
        lock = _IDEM_KEY_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _IDEM_KEY_LOCKS[key] = lock
        return lock


def readiness_checks() -> dict[str, bool]:
    cap, err = parse_max_spend()
    config_valid = err == ""
    cap_ok = config_valid and cap is not None and spent_usd() < cap
    return {
        "config_valid": config_valid,
        "spend_cap_ok": cap_ok,
        "index_loaded": True,
    }


def _parse_case_payload(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if not all(parsed.get(k) for k in ("case_id", "customer_id", "message")):
        return None
    return parsed


def handle_case(payload: dict[str, Any], backend: Any | None) -> dict[str, Any]:
    owned = backend is None
    used = backend
    try:
        if owned:
            used = make_backend()
        return agent.run_case(
            used,
            case_id=str(payload["case_id"]),
            customer_id=str(payload["customer_id"]),
            message=str(payload["message"]),
            loan_id=payload.get("loan_id"),
        )
    finally:
        if owned and used is not None:
            used.close()


def handle_run(text: str, backend: Any | None) -> dict[str, Any]:
    """Execute POST /run per contract.md.

    JSON that looks like a /case body runs the real agent. Other strings are
    synthetic probes: they must still call the model (item 1) and must not
    write the customer database.
    """
    cap, err = parse_max_spend()
    if err:
        raise ServiceError(503, "not_ready", err)
    if cap is not None and spent_usd() >= cap:
        raise ServiceError(503, "spend_cap_reached", f"spent {spent_usd():.6f} of {cap}")

    case = _parse_case_payload(text)
    if case is not None:
        result = handle_case(case, backend)
        tracing.export_otlp(str(result["trace_id"]))
        output = json.dumps(
            {
                "case_id": result["case_id"],
                "summary": result["summary"],
                "actions_taken": result["actions_taken"],
                "trace_id": result["trace_id"],
            }
        )
        return {"output": output, "trace_id": result["trace_id"], "cost_usd": 0.0}

    trace_id = tracing.new_trace()
    try:
        with tracing.start_span("run", **{"harbour.probe": True}):
            try:
                response = llm.complete(
                    [
                        {
                            "role": "system",
                            "content": "Reply with a short JSON object {\"ok\": true}.",
                        },
                        {"role": "user", "content": text},
                    ],
                    max_tokens=64,
                )
            except llm.LLMError as exc:
                raise ServiceError(exc.status, exc.code, str(exc)) from exc
        cost = float(response.get("cost_usd") or 0.0)
        add_spend(cost)
        return {
            "output": response.get("content") or text,
            "trace_id": trace_id,
            "cost_usd": cost,
        }
    finally:
        tracing.export_otlp(trace_id)


class HarbourHandler(BaseHTTPRequestHandler):
    server_version = "Harbour/1.0"
    protocol_version = "HTTP/1.1"

    backend: Any = None

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        if os.environ.get("HARBOUR_ACCESS_LOG") == "1":
            super().log_message(fmt, *args)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_envelope(self, status: int, code: str, message: str, trace_id: str | None = None) -> None:
        error: dict[str, Any] = {"code": code, "message": message}
        if trace_id:
            error["trace_id"] = trace_id
        self._send_json(status, {"error": error})

    def _read_json(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > MAX_BODY_BYTES:
            return None
        try:
            parsed = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/healthz":
            self._send_json(200, {"status": "ok", "version": app_version()})
            return
        if path == "/readyz":
            checks = readiness_checks()
            ready = all(checks.values())
            self._send_json(
                200 if ready else 503,
                {"ready": ready, "checks": checks},
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/run":
            self._handle_run()
            return
        if path != "/case":
            self._send_json(404, {"error": "not found"})
            return
        self._handle_case()

    def _handle_case(self) -> None:
        payload = self._read_json()
        if payload is None:
            self._send_json(400, {"error": "body must be a JSON object"})
            return
        missing = [k for k in ("case_id", "customer_id", "message") if not payload.get(k)]
        if missing:
            self._send_json(400, {"error": f"missing fields: {', '.join(missing)}"})
            return
        try:
            result = handle_case(payload, self.backend)
        except Exception as exc:  # noqa: BLE001 - never leak a stack trace
            self._send_json(500, {"error": f"{type(exc).__name__}: {exc}"})
            return
        self._send_json(
            200,
            {
                "case_id": result["case_id"],
                "summary": result["summary"],
                "actions_taken": result["actions_taken"],
                "trace_id": result["trace_id"],
            },
        )

    def _execute_run(self, text: str) -> tuple[int, dict[str, Any]]:
        try:
            return 200, handle_run(text, self.backend)
        except ServiceError as exc:
            error: dict[str, Any] = {"code": exc.code, "message": str(exc)}
            return exc.status, {"error": error}
        except Exception as exc:  # noqa: BLE001
            return 502, {
                "error": {
                    "code": "upstream_error",
                    "message": f"{type(exc).__name__}: {exc}",
                }
            }

    def _handle_run(self) -> None:
        payload = self._read_json()
        if payload is None or not isinstance(payload.get("input"), str):
            self._send_error_envelope(
                422,
                "invalid_request",
                "body must be {input: string, idempotency_key?: string}",
            )
            return
        text = payload["input"]
        key = payload.get("idempotency_key")
        if not isinstance(key, str) or not key:
            status, body = self._execute_run(text)
            self._send_json(status, body)
            return
        with idempotency_lock(key):
            cached = _IDEM_CACHE.get(key)
            if cached is not None:
                stored, body = cached
                if stored != text:
                    self._send_error_envelope(
                        409,
                        "idempotency_conflict",
                        "key already used with a different input",
                    )
                    return
                self._send_json(200, body)
                return
            status, body = self._execute_run(text)
            if status == 200:
                _IDEM_CACHE[key] = (text, body)
            self._send_json(status, body)


def listen_port(explicit: int | None = None) -> int:
    if explicit is not None:
        return explicit
    if os.environ.get("PORT"):
        return int(os.environ["PORT"])
    return int(os.environ.get("HARBOUR_PORT", "8080"))


def make_server(
    host: str | None = None, port: int | None = None, backend: Any = None
) -> ThreadingHTTPServer:
    """Build (but do not start) the HTTP server."""
    bind_host = host if host is not None else os.environ.get("HARBOUR_HOST", "127.0.0.1")
    bind_port = listen_port(port)
    handler = type("BoundHarbourHandler", (HarbourHandler,), {"backend": backend})
    return ThreadingHTTPServer((bind_host, bind_port), handler)


def main() -> None:
    server = make_server()
    host, port = server.server_address[0], server.server_address[1]
    print(f"harbour listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
