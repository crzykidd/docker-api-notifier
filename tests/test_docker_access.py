import logging
from unittest import mock

import docker
import pytest

import docker_access
import health
import image_info
import network_info

IMG_ID = "sha256:" + "b" * 64


def _api_error(code):
    resp = mock.Mock(status_code=code)
    return docker.errors.APIError("Request forbidden by administrative rules",
                                  response=resp)


def _net_client(error):
    client = mock.Mock()
    client.networks.get.side_effect = error
    return client


def _img_container(error, image_id=IMG_ID):
    c = mock.Mock()
    c.name = "web"
    c.attrs = {"Image": image_id}
    c.client.images.get.side_effect = error
    return c


def _warnings(caplog):
    return [r for r in caplog.records if r.levelno == logging.WARNING]


@pytest.fixture
def clock(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(docker_access.time, "monotonic", lambda: now[0])
    return now


def test_only_exactly_403_is_denied():
    assert docker_access.is_denied_error(_api_error(403))
    assert not docker_access.is_denied_error(_api_error(500))
    assert not docker_access.is_denied_error(RuntimeError("403"))
    assert not docker_access.is_denied_error(
        docker.errors.NotFound("gone", response=mock.Mock(status_code=404)))


def test_network_403_warns_once_and_backs_off(caplog, clock):
    caplog.set_level(logging.DEBUG)
    client = _net_client(_api_error(403))
    for nid in ("n1", "n2", "n3"):
        assert network_info._driver_for(client, nid) is None
    assert client.networks.get.call_count == 1  # backed off after the first
    warns = _warnings(caplog)
    assert len(warns) == 1 and "NETWORKS=1" in warns[0].getMessage()
    assert docker_access.status("networks") == "denied"


def test_network_retries_after_backoff_and_recovers(caplog, clock):
    caplog.set_level(logging.INFO)
    client = _net_client(_api_error(403))
    network_info._driver_for(client, "n1")
    clock[0] += docker_access.BACKOFF_SECONDS + 1
    network_info._driver_for(client, "n1")
    assert client.networks.get.call_count == 2
    assert len(_warnings(caplog)) == 1  # still denied: no second warning

    client.networks.get.side_effect = lambda nid: mock.Mock(attrs={"Driver": "macvlan"})
    clock[0] += docker_access.BACKOFF_SECONDS + 1
    assert network_info._driver_for(client, "n1") == "macvlan"
    assert docker_access.status("networks") == "ok"
    assert any("allowed again" in r.getMessage() and r.levelno == logging.INFO
               for r in caplog.records)

    # Broken again later -> warns again (transition, not once per process).
    client.networks.get.side_effect = _api_error(403)
    network_info._driver_for(client, "n2")
    assert len(_warnings(caplog)) == 2


def test_network_other_errors_stay_debug(caplog, clock):
    caplog.set_level(logging.DEBUG)
    for err in (RuntimeError("boom"), _api_error(500),
                docker.errors.NotFound("gone", response=mock.Mock(status_code=404))):
        client = _net_client(err)
        assert network_info._driver_for(client, "n1") is None
    assert _warnings(caplog) == []
    assert docker_access.status("networks") == "unknown"
    assert not docker_access.should_skip("networks")


def test_image_403_one_warning_no_per_image_spam(caplog, clock):
    caplog.set_level(logging.DEBUG)
    for i in range(3):
        container = _img_container(_api_error(403), image_id=f"sha256:{i}" * 4)
        assert image_info.lookup(container) is None
    warns = _warnings(caplog)
    assert len(warns) == 1 and "IMAGES=1" in warns[0].getMessage()
    assert "Could not look up image" not in warns[0].getMessage()
    assert docker_access.status("images") == "denied"


def test_image_backoff_then_retry_and_recovery(caplog, clock):
    caplog.set_level(logging.INFO)
    c = _img_container(_api_error(403))
    image_info.lookup(c)
    image_info.lookup(c)
    assert c.client.images.get.call_count == 1
    clock[0] += docker_access.BACKOFF_SECONDS + 1
    c.client.images.get.side_effect = None
    c.client.images.get.return_value = mock.Mock(attrs={})
    assert image_info.lookup(c) == {"id": IMG_ID}
    assert docker_access.status("images") == "ok"
    assert any("allowed again" in r.getMessage() for r in caplog.records)


def test_image_other_errors_keep_per_image_warning(caplog, clock):
    caplog.set_level(logging.DEBUG)
    c = _img_container(RuntimeError("boom"))
    image_info.lookup(c)
    image_info.lookup(c)
    warns = _warnings(caplog)
    assert len(warns) == 1 and "Could not look up image" in warns[0].getMessage()
    assert docker_access.status("images") == "unknown"


def test_healthz_docker_permissions(clock):
    client = mock.Mock()
    client.ping.return_value = True
    client.version.return_value = {"Version": "29"}
    health.configure(docker_client=client)
    assert health.snapshot()[0]["docker_permissions"] == {
        "networks": "unknown", "images": "unknown"}
    network_info._driver_for(_net_client(_api_error(403)), "n1")
    image_info.lookup(_img_container(RuntimeError("x")))  # not a 403: stays unknown
    body, code = health.snapshot()
    assert code == 200  # a denial is informational
    assert body["docker_permissions"] == {"networks": "denied", "images": "unknown"}
