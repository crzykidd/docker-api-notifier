from unittest import mock

import pytest
import requests

import main

IMG_ID = "sha256:" + "b" * 64
DIGEST = "ghcr.io/x/app@sha256:" + "a" * 64


def _container(labels=None):
    c = mock.Mock()
    c.name = "web"
    c.id = "cid"
    c.attrs = {
        "Image": IMG_ID,
        "Config": {"Image": "app:latest", "Labels": labels or {
            "dockernotifier.notifiers": "service-tracker-dashboard,dns",
            "dockernotifier.dns.containerhostname": "web",
            "dockernotifier.dns.containerzone": "example.com",
            "dockernotifier.dns.dockerdomain": "docker.example.com",
        }},
        "State": {"Status": "running", "StartedAt": "t"},
        "NetworkSettings": {},
    }
    c.client.images.get.return_value = mock.Mock(attrs={"RepoDigests": [DIGEST]})
    return c


@pytest.fixture
def notifiers(monkeypatch):
    std = mock.Mock()
    dns = mock.Mock()
    monkeypatch.setattr(main, "service_tracker_dashboard", std)
    monkeypatch.setattr(main, "technitium_dns", dns)
    monkeypatch.setattr(main, "STD_CONFIGURED", True)
    monkeypatch.setattr(main, "STD_SEND_IMAGE_INFO", True)
    std.image_info_supported.return_value = True
    return std, dns


def test_image_info_sent_to_std_only(notifiers):
    std, dns = notifiers
    main.handle_container_event(_container(), "host", "start")
    assert std.register.call_args.kwargs["image_info"]["repo_digests"] == [DIGEST]
    assert "image_info" not in dns.register.call_args.kwargs


def test_unsupported_std_skips_lookup(notifiers):
    std, _ = notifiers
    std.image_info_supported.return_value = False
    c = _container()
    main.handle_container_event(c, "host", "start")
    assert "image_info" not in std.register.call_args.kwargs
    c.client.images.get.assert_not_called()


def test_opt_out_env(notifiers, monkeypatch):
    std, _ = notifiers
    monkeypatch.setattr(main, "STD_SEND_IMAGE_INFO", False)
    c = _container()
    main.handle_container_event(c, "host", "start")
    assert "image_info" not in std.register.call_args.kwargs
    c.client.images.get.assert_not_called()


def test_lookup_failure_still_registers_without_image_info(notifiers):
    std, _ = notifiers
    c = _container()
    c.client.images.get.side_effect = requests.ConnectionError("gone")
    main.handle_container_event(c, "host", "refresh")
    std.register.assert_called_once()
    assert "image_info" not in std.register.call_args.kwargs


def test_image_info_label_does_not_leak(notifiers):
    std, _ = notifiers
    std.image_info_supported.return_value = False
    c = _container({"dockernotifier.notifiers": "service-tracker-dashboard",
                    "dockernotifier.std.image_info": "evil"})
    main.handle_container_event(c, "host", "start")
    assert "image_info" not in std.register.call_args.kwargs


def test_send_image_info_env_parsing(monkeypatch):
    monkeypatch.setenv("STD_SEND_IMAGE_INFO", "false")
    assert main._parse_bool_env("STD_SEND_IMAGE_INFO", default=True) is False
    monkeypatch.delenv("STD_SEND_IMAGE_INFO")
    assert main._parse_bool_env("STD_SEND_IMAGE_INFO", default=True) is True


# --- std.* labels, skip, network details ----------------------------------

STD_ONLY = {"dockernotifier.notifiers": "service-tracker-dashboard"}


def _std_container(extra=None, networks=None):
    c = _container({**STD_ONLY, **(extra or {})})
    c.attrs["NetworkSettings"] = {"Networks": networks or {}}
    return c


def test_colliding_label_does_not_crash_and_warns(notifiers, caplog):
    std, _ = notifiers
    c = _std_container({"dockernotifier.std.container_name": "evil",
                        "dockernotifier.std.networks": "x",
                        "dockernotifier.std.timestamp": "yesterday",
                        "dockernotifier.std.group": "media"})
    with caplog.at_level("WARNING"):
        main.handle_container_event(c, "host", "start")
    kw = std.register.call_args.kwargs
    assert kw["container_name"] == "web" and kw["group"] == "media"
    assert "timestamp" not in kw and kw["networks"] == []
    warned = " ".join(r.message for r in caplog.records)
    assert "web" in warned and "dockernotifier.std.container_name" in warned
    assert "dockernotifier.std.timestamp" in warned


def test_std_host_label_dropped_with_pointer(notifiers, caplog):
    std, _ = notifiers
    c = _std_container({"dockernotifier.std.host": "other"})
    with caplog.at_level("WARNING"):
        main.handle_container_event(c, "host", "start")
    assert std.register.call_args.kwargs["docker_host"] == "host"
    assert "host" not in std.register.call_args.kwargs
    assert any("HOST_NAME_OVERRIDE" in r.message for r in caplog.records)


def test_skip_stops_std_even_with_report_all(notifiers, monkeypatch):
    std, _ = notifiers
    monkeypatch.setattr(main, "STD_REPORT_ALL_CONTAINERS", True)
    c = _container({"dockernotifier.std.skip": "true"})
    main.handle_container_event(c, "host", "start")
    std.register.assert_not_called()


def test_skip_does_not_affect_dns(notifiers):
    std, dns = notifiers
    c = _container({**_container().attrs["Config"]["Labels"],
                    "dockernotifier.std.skip": "yes"})
    main.handle_container_event(c, "host", "start")
    std.register.assert_not_called()
    dns.register.assert_called_once()


def test_skip_false_or_typo_still_reports_and_skip_not_forwarded(notifiers):
    std, _ = notifiers
    for value in ("false", "maybe"):
        std.register.reset_mock()
        main.handle_container_event(
            _std_container({"dockernotifier.std.skip": value}), "host", "start")
        assert "skip" not in std.register.call_args.kwargs


def test_network_details_collected_for_std(notifiers):
    std, _ = notifiers
    c = _std_container(networks={"lan": {
        "Aliases": None, "NetworkID": "n1", "IPAddress": "192.168.1.50",
        "GlobalIPv6Address": "", "MacAddress": "02:42:ac:11:00:02"}})
    c.client.networks.get.return_value = mock.Mock(attrs={"Driver": "macvlan"})
    main.handle_container_event(c, "host", "start")
    assert std.register.call_args.kwargs["networks"] == [{
        "name": "lan", "aliases": [], "driver": "macvlan",
        "ip_address": "192.168.1.50", "mac_address": "02:42:ac:11:00:02"}]


def test_dns_only_makes_no_network_lookups(notifiers):
    std, dns = notifiers
    labels = {k: v for k, v in _container().attrs["Config"]["Labels"].items()}
    labels["dockernotifier.notifiers"] = "dns"
    c = _container(labels)
    c.attrs["NetworkSettings"] = {"Networks": {"lan": {"NetworkID": "n1"}}}
    main.handle_container_event(c, "host", "start")
    dns.register.assert_called_once()
    c.client.networks.get.assert_not_called()
