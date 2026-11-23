import logging
from unittest import mock

import pytest
import requests

import health
import main
from notifiers import technitium_dns as dns

ADD_URL = "http://dns.test:5380/api/zones/records/add"
TOKEN = "s3cr3t-token"
FQDN = "web.example.com"
VALUE = "host1.docker.example.com"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("DNS_SERVER_URL", ADD_URL)
    monkeypatch.setenv("DNS_SERVER_API_TOKEN", TOKEN)
    monkeypatch.setattr(dns, "_warned_url", False)
    monkeypatch.setattr(dns._do_dns_update.retry, "sleep", lambda s: None)


def _resp(body, status=200):
    r = mock.Mock()
    r.status_code = status
    r.text = str(body)
    r.json.return_value = body
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError("boom", response=r)
    return r


def _get_body(cname=VALUE, ttl=300, name=FQDN):
    return {"status": "ok", "response": {"records": [
        {"name": name, "type": "CNAME", "ttl": ttl, "rData": {"cname": cname}}]}}


def _register():
    dns.register(container_fqdn=FQDN, zone="example.com", value=VALUE,
                 container_name="web", action="start")


def _fake_get(get_resp, add_resp=None):
    calls = []

    def fake(url, params=None, timeout=None):
        calls.append(url)
        if url.endswith("/records/get"):
            if isinstance(get_resp, Exception):
                raise get_resp
            return get_resp
        return add_resp or _resp({"status": "ok", "response": {"addedRecord": {}}})

    return fake, calls


def _adds(calls):
    return [c for c in calls if c.endswith("/records/add")]


def test_skip_when_unchanged(monkeypatch):
    fake, calls = _fake_get(_resp(_get_body(cname=VALUE.upper() + ".")))
    monkeypatch.setattr(requests, "get", fake)
    _register()
    assert _adds(calls) == []
    assert health._notifiers["dns"]["success_count"] == 1


def test_add_when_target_differs(monkeypatch):
    fake, calls = _fake_get(_resp(_get_body(cname="other.example.com")))
    monkeypatch.setattr(requests, "get", fake)
    _register()
    assert len(_adds(calls)) == 1


def test_add_when_ttl_differs(monkeypatch):
    fake, calls = _fake_get(_resp(_get_body(ttl=3600)))
    monkeypatch.setattr(requests, "get", fake)
    _register()
    assert len(_adds(calls)) == 1


def test_add_when_lookup_errors_and_no_token_logged(monkeypatch, caplog):
    err = requests.ConnectionError(f"failed http://dns.test:5380/api/zones/records/get?token={TOKEN}&domain=x")
    fake, calls = _fake_get(err)
    monkeypatch.setattr(requests, "get", fake)
    with caplog.at_level(logging.DEBUG):
        _register()
    assert len(_adds(calls)) == 1
    assert TOKEN not in caplog.text
    assert health._notifiers["dns"]["error_count"] == 0


def test_add_when_lookup_status_error(monkeypatch):
    fake, calls = _fake_get(_resp({"status": "error", "errorMessage": "no zone"}))
    monkeypatch.setattr(requests, "get", fake)
    _register()
    assert len(_adds(calls)) == 1


def test_no_lookup_when_url_not_add_endpoint(monkeypatch):
    monkeypatch.setenv("DNS_SERVER_URL", "http://dns.test:5380/custom")
    fake, calls = _fake_get(_resp(_get_body()))
    monkeypatch.setattr(requests, "get", fake)
    _register()
    assert calls == ["http://dns.test:5380/custom"]


def test_info_line_is_short_and_not_raw_json(monkeypatch, caplog):
    fake, _ = _fake_get(_resp({"status": "ok", "response": {"records": []}}))
    monkeypatch.setattr(requests, "get", fake)
    with caplog.at_level(logging.INFO):
        _register()
    infos = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert infos == [f"DNS record {FQDN} CNAME {VALUE}: set"]


def test_status_error_reply_is_failure(monkeypatch, caplog):
    fake, _ = _fake_get(_resp({"status": "ok", "response": {"records": []}}),
                        _resp({"status": "error", "errorMessage": f"bad token={TOKEN}"}))
    monkeypatch.setattr(requests, "get", fake)
    with caplog.at_level(logging.INFO):
        _register()
    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert TOKEN not in caplog.text
    assert health._notifiers["dns"]["error_count"] == 1
    assert health._notifiers["dns"]["success_count"] == 0


def test_notifier_modules_log_dispatch_at_debug(monkeypatch, caplog):
    fake, _ = _fake_get(_resp(_get_body()))
    monkeypatch.setattr(requests, "get", fake)
    with caplog.at_level(logging.INFO):
        _register()
    assert "triggered" not in caplog.text
    with caplog.at_level(logging.DEBUG):
        _register()
    assert 'DNS notifier triggered for "web" due to "start"' in caplog.text


def test_one_info_dispatch_line_per_notifier(caplog):
    from tests.test_dispatch import _container
    sd, dd = mock.Mock(), mock.Mock()
    sd.image_info_supported.return_value = False
    with mock.patch.object(main, "service_tracker_dashboard", sd), \
            mock.patch.object(main, "technitium_dns", dd), \
            mock.patch.object(main, "STD_CONFIGURED", True), \
            caplog.at_level(logging.INFO):
        main.handle_container_event(_container(), "host", "start")
    lines = [r.getMessage() for r in caplog.records if "notifier triggered" in r.getMessage()]
    assert sorted(m.split()[0] for m in lines) == ["DNS", "STD"]


def test_refresh_loop_sleeps_before_first_pass(monkeypatch):
    client = mock.Mock()
    client.containers.list.return_value = [mock.Mock(name="c1")]
    monkeypatch.setattr(main.docker, "from_env", lambda: client)
    handled = mock.Mock()
    monkeypatch.setattr(main, "handle_container_event", handled)

    class Stop(Exception):
        pass

    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) == 1:
            raise Stop

    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    with pytest.raises(Stop):
        main.periodic_update_loop("host")
    assert sleeps == [main.STD_REFRESH_SECONDS]
    handled.assert_not_called()
    assert health._refresh["last_run_at"] is None
