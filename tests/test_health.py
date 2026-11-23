import json
import urllib.error
import urllib.request
from unittest import mock

import pytest
import requests

import health
from notifiers import service_tracker_dashboard as std
from notifiers import technitium_dns as dns

DNS_TOKEN = "dns-secret-token-123"
STD_TOKEN = "std-secret-token-456"


class FakeDocker:
    def __init__(self, ok=True):
        self.ok = ok
        self.pings = 0

    def ping(self):
        self.pings += 1
        if not self.ok:
            raise ConnectionError("docker down")
        return True

    def version(self):
        return {"Version": "29.9.3"}


@pytest.fixture
def docker_ok():
    client = FakeDocker()
    health.configure(version="0.5.0", host="h1", docker_client=client,
                     refresh_enabled=True, refresh_interval=60,
                     interpreters=["dockflare", "traefik"])
    return client


def test_snapshot_shape_and_values(docker_ok):
    health.record_event()
    health.record_refresh()
    body, code = health.snapshot()
    assert code == 200
    assert body["status"] == "ok"
    assert body["version"] == "0.5.0"
    assert body["host"] == "h1"
    assert body["started_at"].endswith("Z")
    assert isinstance(body["uptime_seconds"], int)
    assert body["docker"]["connected"] is True
    assert body["docker"]["server_version"] == "29.9.3"
    assert body["docker"]["events_seen"] == 1
    assert body["docker"]["last_event_at"].endswith("Z")
    assert body["refresh_loop"]["enabled"] is True
    assert body["refresh_loop"]["interval_seconds"] == 60
    assert body["refresh_loop"]["last_run_at"].endswith("Z")
    assert body["interpreters"] == ["dockflare", "traefik"]
    n = body["notifiers"]
    assert n["dns"]["configured"] is False
    assert n["dns"]["success_count"] == 0 and n["dns"]["last_error"] is None
    s = n["service_tracker_dashboard"]
    assert s["configured"] is True  # conftest sets STD_URL/STD_API_TOKEN
    assert s["std_version"] is None and s["api_revision"] is None
    assert s["image_info_supported"] is None  # no /meta check yet
    assert s["features_supported"] == {"image_info": None, "network_details": None}
    json.dumps(body)


def test_std_fields_come_from_gate_state(docker_ok):
    with std._state_lock:
        std._state.update(std_version="0.12.0", api_revision=5,
                          image_info_supported=True, last_check=1000.0)
    s = health.snapshot()[0]["notifiers"]["service_tracker_dashboard"]
    assert (s["std_version"], s["api_revision"], s["image_info_supported"]) == ("0.12.0", 5, True)
    assert s["features_supported"] == {"image_info": True, "network_details": False}


def test_dns_configured_reflects_env(docker_ok, monkeypatch):
    monkeypatch.setenv("DNS_SERVER_URL", "http://dns.test")
    assert health.snapshot()[0]["notifiers"]["dns"]["configured"] is False
    monkeypatch.setenv("DNS_SERVER_API_TOKEN", DNS_TOKEN)
    assert health.snapshot()[0]["notifiers"]["dns"]["configured"] is True


def test_503_when_docker_unreachable():
    health.configure(docker_client=FakeDocker(ok=False))
    body, code = health.snapshot()
    assert code == 503
    assert body["status"] == "unhealthy"
    assert body["docker"]["connected"] is False


def test_503_without_docker_client():
    assert health.snapshot()[1] == 503


def test_503_when_event_loop_stopped(docker_ok):
    health.set_event_loop(True)
    assert health.snapshot()[1] == 200
    health.set_event_loop(False)
    assert health.snapshot()[1] == 503


def test_ping_is_cached(docker_ok):
    health.snapshot()
    health.snapshot()
    assert docker_ok.pings == 1


def test_downstream_errors_keep_200(docker_ok):
    for _ in range(3):
        health.record_error("dns", requests.ConnectionError("dns unreachable"))
        health.record_error("service_tracker_dashboard", requests.Timeout("std slow"))
    health.record_success("dns")
    body, code = health.snapshot()
    assert code == 200 and body["status"] == "ok"
    d = body["notifiers"]["dns"]
    assert (d["success_count"], d["error_count"]) == (1, 3)
    assert d["last_error"].startswith("ConnectionError: dns unreachable")
    assert d["last_error_at"].endswith("Z") and d["last_success_at"].endswith("Z")
    assert body["notifiers"]["service_tracker_dashboard"]["error_count"] == 3


def test_error_string_is_truncated():
    health.record_error("dns", RuntimeError("x" * 1000))
    body = health.snapshot()[0]
    assert len(body["notifiers"]["dns"]["last_error"]) <= 200


def test_no_secret_in_snapshot_even_from_exception_urls(docker_ok, monkeypatch):
    monkeypatch.setenv("DNS_SERVER_URL", "http://dns.test/api")
    monkeypatch.setenv("DNS_SERVER_API_TOKEN", DNS_TOKEN)
    monkeypatch.setenv("STD_API_TOKEN", STD_TOKEN)
    # requests embeds the full URL (token in the query string) in errors.
    monkeypatch.setattr(dns.requests, "get", mock.Mock(
        side_effect=requests.ConnectionError(
            f"HTTPConnectionPool: Max retries exceeded with url: "
            f"/api?token={DNS_TOKEN}&domain=a.b (Caused by x)")))
    monkeypatch.setattr(dns._do_dns_update.retry, "sleep", lambda s: None)
    dns.register(container_fqdn="a.b", zone="b", value="h.c", container_name="c")
    monkeypatch.setattr(std.requests, "post", mock.Mock(
        side_effect=requests.ConnectionError(
            f"https://user:{STD_TOKEN}@std.test/x?api_key={STD_TOKEN} failed")))
    std.register(container_name="web", docker_host="h")
    text = json.dumps(health.snapshot()[0])
    assert DNS_TOKEN not in text and STD_TOKEN not in text
    assert health.snapshot()[0]["notifiers"]["dns"]["error_count"] == 1
    assert health.snapshot()[0]["notifiers"]["service_tracker_dashboard"]["error_count"] == 1


def test_dns_failure_log_line_has_no_token(monkeypatch, caplog):
    monkeypatch.setenv("DNS_SERVER_URL", "http://dns.test/api")
    monkeypatch.setenv("DNS_SERVER_API_TOKEN", DNS_TOKEN)
    monkeypatch.setattr(dns.requests, "get", mock.Mock(
        side_effect=requests.ConnectionError(
            f"Max retries exceeded with url: /api?token={DNS_TOKEN}&domain=a.b")))
    monkeypatch.setattr(dns._do_dns_update.retry, "sleep", lambda s: None)
    monkeypatch.setattr(dns.logger, "propagate", True)
    with caplog.at_level("ERROR", logger=dns.logger.name):
        dns.register(container_fqdn="a.b", zone="b", value="h.c", container_name="c")
    assert "DNS update failed for c" in caplog.text
    assert DNS_TOKEN not in caplog.text


def test_notifier_register_records_success(monkeypatch):
    monkeypatch.setenv("DNS_SERVER_URL", "http://dns.test/api")
    monkeypatch.setenv("DNS_SERVER_API_TOKEN", DNS_TOKEN)
    ok = requests.Response()
    ok.status_code = 200
    ok._content = b"{}"
    monkeypatch.setattr(dns.requests, "get", mock.Mock(return_value=ok))
    dns.register(container_fqdn="a.b", zone="b", value="h.c", container_name="c")
    monkeypatch.setattr(std.requests, "post", mock.Mock(return_value=ok))
    monkeypatch.setattr(std.requests, "get", mock.Mock(return_value=ok))
    std.register(container_name="web", docker_host="h")
    n = health.snapshot()[0]["notifiers"]
    assert n["dns"]["success_count"] == 1
    assert n["service_tracker_dashboard"]["success_count"] == 1


@pytest.mark.parametrize("raw,expected", [
    (None, 8080), ("", 8080), ("9000", 9000), ("0", 0),
    ("garbage", 8080), ("-1", 8080), ("70000", 8080),
])
def test_parse_port(raw, expected):
    assert health.parse_port(raw) == expected


def test_start_from_env_disabled(monkeypatch):
    monkeypatch.setenv("HEALTH_PORT", "0")
    with mock.patch.object(health, "start_server") as start:
        assert health.start_from_env() is None
        start.assert_not_called()


def test_bind_failure_returns_none():
    first = health.start_server(0, host="127.0.0.1")
    try:
        port = first.server_address[1]
        assert health.start_server(port, host="127.0.0.1") is None
    finally:
        first.shutdown()
        first.server_close()


@pytest.fixture
def server(docker_ok):
    srv = health.start_server(0, host="127.0.0.1")
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def test_server_answers_healthz(server):
    with urllib.request.urlopen(f"{server}/healthz", timeout=5) as r:
        assert r.status == 200
        assert r.headers["Content-Type"] == "application/json"
        assert json.load(r)["status"] == "ok"


def test_server_503_when_docker_down(server):
    health.configure(docker_client=FakeDocker(ok=False))
    with health._lock:
        health._docker["ping_at"] = None
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{server}/healthz", timeout=5)
    assert exc.value.code == 503
    assert json.load(exc.value)["status"] == "unhealthy"


def test_server_404(server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{server}/nope", timeout=5)
    assert exc.value.code == 404
    assert json.load(exc.value) == {"error": "not found"}


def test_server_head(server):
    req = urllib.request.Request(f"{server}/healthz", method="HEAD")
    with urllib.request.urlopen(req, timeout=5) as r:
        assert r.status == 200 and r.read() == b""


# --- HEALTH_ALLOWED_IPS ---------------------------------------------------

def _nets(*items):
    import ipaddress
    return tuple(ipaddress.ip_network(i) for i in items)


def test_parse_allowed_unset_is_open():
    assert health.parse_allowed_ips(None) is None
    assert health.parse_allowed_ips("") is None
    assert health.parse_allowed_ips("  ") is None


def test_parse_allowed_mixed_separators_and_families():
    got = health.parse_allowed_ips("10.100.18.10, 10.100.20.0/24\nfd00::/8  192.168.1.5/24")
    assert {str(n) for n in got} >= {"10.100.18.10/32", "10.100.20.0/24",
                                     "fd00::/8", "192.168.1.0/24"}


def test_parse_allowed_skips_invalid_with_warning(caplog):
    with caplog.at_level("WARNING", logger="health"):
        got = health.parse_allowed_ips("10.0.0.1,bogus,300.1.1.1")
    assert "10.0.0.1/32" in {str(n) for n in got}
    assert "bogus" in caplog.text and "300.1.1.1" in caplog.text


def test_parse_allowed_all_invalid_fails_closed(caplog):
    with caplog.at_level("ERROR", logger="health"):
        got = health.parse_allowed_ips("nope, also-nope")
    assert got == health.LOOPBACK_NETWORKS
    assert "failing closed" in caplog.text
    assert not health.client_allowed("10.0.0.1", got)
    assert health.client_allowed("127.0.0.1", got)


@pytest.mark.parametrize("addr,ok", [
    ("10.100.18.10", True), ("10.100.20.77", True), ("10.100.21.1", False),
    ("fd00::5", True), ("fe80::1", False),
    ("::ffff:10.100.18.10", True), ("::ffff:10.9.9.9", False),
    ("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("not-an-ip", False),
])
def test_client_allowed(addr, ok):
    allowed = health.parse_allowed_ips("10.100.18.10, 10.100.20.0/24, fd00::/8")
    assert health.client_allowed(addr, allowed) is ok


def test_client_allowed_none_is_open():
    assert health.client_allowed("8.8.8.8", None)


@pytest.fixture
def restricted(docker_ok):
    """Server restricted to an address the test client (127.0.0.1) is not in
    is useless because loopback is always allowed, so fake the peer address."""
    srv = health.start_server(0, host="127.0.0.1",
                              allowed=health.parse_allowed_ips("10.1.1.1"))
    yield f"http://127.0.0.1:{srv.server_address[1]}", srv
    srv.shutdown()
    srv.server_close()


def test_loopback_allowed_when_restricted(restricted):
    url, _ = restricted
    with urllib.request.urlopen(f"{url}/healthz", timeout=5) as r:
        assert r.status == 200


def _fake_peer(ip):
    """Make every handler see `ip` as the TCP peer (loopback is the real one)."""
    return mock.patch.object(
        health._Handler, "client_address",
        property(lambda self: (ip, 1234), lambda self, value: None), create=True)


@pytest.mark.parametrize("peer,method,code", [
    ("10.1.1.1", "GET", 200), ("10.1.1.1", "HEAD", 200),
    ("10.2.2.2", "GET", 403), ("10.2.2.2", "HEAD", 403),
])
def test_peer_filtering(restricted, peer, method, code):
    url, _ = restricted
    with _fake_peer(peer), \
            mock.patch.object(health, "snapshot", wraps=health.snapshot) as snap:
        req = urllib.request.Request(f"{url}/healthz", method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                status, body = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read()
        assert status == code
        if code == 403:
            snap.assert_not_called()
            assert body == (b"" if method == "HEAD" else b'{"error": "forbidden"}')
        else:
            snap.assert_called_once()


def test_denied_gets_403_for_unknown_path(restricted):
    url, _ = restricted
    with _fake_peer("10.2.2.2"):
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(f"{url}/nope", timeout=5)
    assert exc.value.code == 403


def test_start_from_env_passes_allowlist(monkeypatch):
    monkeypatch.setenv("HEALTH_PORT", "9999")
    monkeypatch.setenv("HEALTH_ALLOWED_IPS", "10.0.0.0/8")
    with mock.patch.object(health, "start_server") as start:
        health.start_from_env()
    allowed = start.call_args.kwargs["allowed"]
    assert "10.0.0.0/8" in {str(n) for n in allowed}


def test_start_from_env_unset_is_open(monkeypatch):
    monkeypatch.setenv("HEALTH_PORT", "9999")
    monkeypatch.delenv("HEALTH_ALLOWED_IPS", raising=False)
    with mock.patch.object(health, "start_server") as start:
        health.start_from_env()
    assert start.call_args.kwargs["allowed"] is None
