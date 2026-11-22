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
