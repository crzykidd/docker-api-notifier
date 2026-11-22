"""
Health state and the `/healthz` HTTP endpoint.

Holds the counters and timestamps behind a lock (the event loop, the
refresh thread and the HTTP thread all touch them), builds the JSON
snapshot, and runs a stdlib `ThreadingHTTPServer` in a daemon thread.

Recorders (`record_event`, `record_refresh`, `record_success`,
`record_error`) are called from `main.py` and from each notifier's
`register()` on its final outcome. Health is an add-on: nothing here may
stop the notifier from notifying, so recorder and server failures never
propagate.

Semantics: HTTP 200 / `"ok"` when Docker answers a ping and the event
loop (once started) is running; HTTP 503 / `"unhealthy"` otherwise.
Downstream (STD, Technitium) failures only show in the per-notifier
fields and never make the notifier unhealthy.

Environment variables:
    HEALTH_PORT  TCP port for the endpoint. Default 8080. 0 disables it.
"""

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from logging_setup import get_logger

logger = get_logger("health")

DEFAULT_PORT = 8080
PING_CACHE_SECONDS = 15
MAX_ERROR_CHARS = 200

_lock = threading.Lock()
_started = time.time()
_ctx = {
    "version": "unknown",
    "host": None,
    "refresh_enabled": False,
    "refresh_interval": None,
    "interpreters": [],
    "docker_client": None,
}
_docker = {
    "last_event_at": None,
    "events_seen": 0,
    "loop_state": "not_started",  # not_started | running | stopped
    "ping_at": None,              # monotonic time of the cached ping
    "ping_ok": False,
    "server_version": None,
}
_refresh = {"last_run_at": None}
_notifiers = {}


def _fresh_notifier():
    return {
        "last_success_at": None, "last_error_at": None, "last_error": None,
        "success_count": 0, "error_count": 0,
    }


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def reset():
    """Reset all state (tests)."""
    global _started
    with _lock:
        _started = time.time()
        _ctx.update(version="unknown", host=None, refresh_enabled=False,
                    refresh_interval=None, interpreters=[], docker_client=None)
        _docker.update(last_event_at=None, events_seen=0, loop_state="not_started",
                       ping_at=None, ping_ok=False, server_version=None)
        _refresh["last_run_at"] = None
        _notifiers.clear()


def configure(*, version=None, host=None, refresh_enabled=None,
              refresh_interval=None, interpreters=None, docker_client=None):
    """Set static context shown in the snapshot. Only non-None args apply."""
    with _lock:
        for key, value in (("version", version), ("host", host),
                           ("refresh_enabled", refresh_enabled),
                           ("refresh_interval", refresh_interval),
                           ("interpreters", interpreters),
                           ("docker_client", docker_client)):
            if value is not None:
                _ctx[key] = value


# --- recorders ------------------------------------------------------------

def record_event():
    with _lock:
        _docker["events_seen"] += 1
        _docker["last_event_at"] = _now_iso()


def record_refresh():
    with _lock:
        _refresh["last_run_at"] = _now_iso()


def set_event_loop(running):
    with _lock:
        _docker["loop_state"] = "running" if running else "stopped"


def record_success(notifier):
    with _lock:
        n = _notifiers.setdefault(notifier, _fresh_notifier())
        n["success_count"] += 1
        n["last_success_at"] = _now_iso()


def sanitize_error(exc):
    """Short `ClassName: message`, with credentials scrubbed, <= 200 chars.

    Exception text from `requests` embeds the full URL; the DNS token rides
    in its query string, so URLs are cut at `?` and userinfo, `token=` values
    are masked, and any configured secret value is replaced outright.
    """
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"(?i)(token|key|secret|password)=[^&\s'\")]*", r"\1=***", text)
    text = re.sub(r"(https?://)[^/\s'\"@]*@", r"\1", text)
    text = re.sub(r"(https?://[^\s'\"?]*)\?[^\s'\")]*", r"\1", text)
    for name in ("DNS_SERVER_API_TOKEN", "STD_API_TOKEN"):
        secret = os.environ.get(name)
        if secret:
            text = text.replace(secret, "***")
    return text[:MAX_ERROR_CHARS]


def record_error(notifier, exc):
    message = sanitize_error(exc)
    with _lock:
        n = _notifiers.setdefault(notifier, _fresh_notifier())
        n["error_count"] += 1
        n["last_error_at"] = _now_iso()
        n["last_error"] = message


# --- snapshot -------------------------------------------------------------

def _docker_alive():
    """Ping Docker, cached for PING_CACHE_SECONDS. Returns (ok, server_version)."""
    with _lock:
        client = _ctx["docker_client"]
        cached = _docker["ping_at"]
        if cached is not None and time.monotonic() - cached < PING_CACHE_SECONDS:
            return _docker["ping_ok"], _docker["server_version"]
    ok = False
    version = None
    if client is not None:
        try:
            ok = bool(client.ping())
            if ok:
                version = (client.version() or {}).get("Version")
        except Exception as e:
            logger.debug(f"Docker ping failed: {sanitize_error(e)}")
    with _lock:
        _docker["ping_at"] = time.monotonic()
        _docker["ping_ok"] = ok
        if ok:
            _docker["server_version"] = version or _docker["server_version"]
        return ok, _docker["server_version"]


def snapshot():
    """Build the health JSON body. Returns (body_dict, http_status)."""
    from notifiers import service_tracker_dashboard as std

    connected, server_version = _docker_alive()
    std_state = std.std_status()
    checked = std_state.get("last_check") is not None

    with _lock:
        loop_state = _docker["loop_state"]
        healthy = connected and loop_state != "stopped"
        body = {
            "status": "ok" if healthy else "unhealthy",
            "version": _ctx["version"],
            "started_at": datetime.fromtimestamp(_started, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"),
            "uptime_seconds": int(time.time() - _started),
            "host": _ctx["host"],
            "docker": {
                "connected": connected,
                "server_version": server_version,
                "last_event_at": _docker["last_event_at"],
                "events_seen": _docker["events_seen"],
            },
            "refresh_loop": {
                "enabled": _ctx["refresh_enabled"],
                "interval_seconds": _ctx["refresh_interval"],
                "last_run_at": _refresh["last_run_at"],
            },
            "interpreters": list(_ctx["interpreters"]),
            "notifiers": {
                "dns": {
                    "configured": bool(os.environ.get("DNS_SERVER_URL")
                                       and os.environ.get("DNS_SERVER_API_TOKEN")),
                    **_notifiers.get("dns", _fresh_notifier()),
                },
                "service_tracker_dashboard": {
                    "configured": std.is_configured(),
                    "std_version": std_state.get("std_version"),
                    "api_revision": std_state.get("api_revision"),
                    "image_info_supported": (
                        std_state.get("image_info_supported") if checked else None),
                    **_notifiers.get("service_tracker_dashboard", _fresh_notifier()),
                },
            },
        }
    return body, (200 if healthy else 503)


# --- HTTP server ----------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "docker-api-notifier-health"

    def log_message(self, format, *args):
        # A 30 s Docker healthcheck would flood the log at info level.
        logger.debug("health http: " + (format % args))

    def _send(self, status, body, head_only=False):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def _handle(self, head_only):
        if self.path.split("?", 1)[0] == "/healthz":
            try:
                body, status = snapshot()
            except Exception as e:
                logger.error(f"Health snapshot failed: {sanitize_error(e)}")
                body, status = {"status": "unhealthy", "error": "snapshot failed"}, 503
            self._send(status, body, head_only)
        else:
            self._send(404, {"error": "not found"}, head_only)

    def do_GET(self):
        self._handle(False)

    def do_HEAD(self):
        self._handle(True)


def parse_port(raw):
    """HEALTH_PORT value -> int. None/garbage/out of range -> default; 0 disables."""
    if raw is None or not str(raw).strip():
        return DEFAULT_PORT
    try:
        port = int(str(raw).strip())
    except ValueError:
        logger.warning(f"Invalid HEALTH_PORT={raw!r}; using default {DEFAULT_PORT}")
        return DEFAULT_PORT
    if not 0 <= port <= 65535:
        logger.warning(f"HEALTH_PORT={raw!r} out of range; using default {DEFAULT_PORT}")
        return DEFAULT_PORT
    return port


def start_server(port, host="0.0.0.0"):
    """Start the endpoint in a daemon thread. Returns the server, or None on bind failure."""
    try:
        server = ThreadingHTTPServer((host, port), _Handler)
    except OSError as e:
        logger.error(f"Health endpoint could not bind port {port}: {e}; continuing without it")
        return None
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="health-http", daemon=True).start()
    logger.info(f"Health endpoint listening on {host}:{server.server_address[1]} (/healthz)")
    return server


def start_from_env():
    """Start the server per HEALTH_PORT. Returns the server or None (disabled / bind failed)."""
    port = parse_port(os.environ.get("HEALTH_PORT"))
    if port == 0:
        logger.info("HEALTH_PORT=0 — health endpoint disabled")
        return None
    return start_server(port)
