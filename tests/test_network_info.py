from unittest import mock

import network_info
from tests.test_dispatch import _container  # noqa: F401  (shared fake)


def _client(drivers=None, fail=False):
    client = mock.Mock()

    def get(network_id):
        if fail:
            raise RuntimeError("denied")
        return mock.Mock(attrs={"Driver": (drivers or {}).get(network_id, "bridge")})

    client.networks.get.side_effect = get
    return client


def _attrs(**nets):
    return {"NetworkSettings": {"Networks": nets}}


def _net(**kw):
    base = {"Aliases": None, "NetworkID": "n1", "IPAddress": "", "GlobalIPv6Address": "",
            "MacAddress": ""}
    base.update(kw)
    return base


def test_collects_ipv4_ipv6_mac_and_driver():
    out = network_info.collect(_attrs(lan=_net(
        Aliases=["a"], IPAddress="192.168.1.50", GlobalIPv6Address="fd00::2",
        MacAddress="02:42:ac:11:00:02")), _client({"n1": "macvlan"}))
    assert out == [{"name": "lan", "aliases": ["a"], "driver": "macvlan",
                    "ip_address": "192.168.1.50", "ipv6_address": "fd00::2",
                    "mac_address": "02:42:ac:11:00:02"}]


def test_empty_values_are_left_out():
    out = network_info.collect(_attrs(n=_net()), _client({"n1": "bridge"}))
    assert out == [{"name": "n", "aliases": [], "driver": "bridge"}]


def test_invalid_values_left_out():
    out = network_info.collect(_attrs(n=_net(
        IPAddress="999.1.1.1", GlobalIPv6Address="192.168.1.1",
        MacAddress="not-a-mac")), _client({"n1": "x" * 33}))
    assert out == [{"name": "n", "aliases": []}]


def test_wrong_family_ipv4_rejected():
    out = network_info.collect(_attrs(n=_net(IPAddress="fd00::2")), _client())
    assert "ip_address" not in out[0]


def test_driver_cached_across_containers():
    client = _client({"n1": "macvlan"})
    a = _attrs(lan=_net(IPAddress="10.0.0.2"))
    b = _attrs(lan=_net(IPAddress="10.0.0.3"))
    network_info.collect(a, client)
    network_info.collect(b, client)
    assert client.networks.get.call_count == 1


def test_driver_lookup_failure_leaves_driver_out_and_is_not_cached():
    client = _client(fail=True)
    out = network_info.collect(_attrs(n=_net(IPAddress="10.0.0.2")), client)
    assert out == [{"name": "n", "aliases": [], "ip_address": "10.0.0.2"}]
    network_info.collect(_attrs(n=_net()), client)
    assert client.networks.get.call_count == 2


def test_host_network():
    out = network_info.collect(_attrs(host=_net(NetworkID="h1")), _client({"h1": "host"}))
    assert out == [{"name": "host", "aliases": [], "driver": "host"}]


def test_no_client_means_plain_items_and_no_lookups():
    out = network_info.collect(_attrs(lan=_net(IPAddress="10.0.0.2")), None)
    assert out == [{"name": "lan", "aliases": []}]


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(network_info, "CACHE_MAX_ENTRIES", 2)
    client = _client()
    for i in range(5):
        network_info.collect(_attrs(n=_net(NetworkID=f"id{i}")), client)
    assert len(network_info._driver_cache) == 2
