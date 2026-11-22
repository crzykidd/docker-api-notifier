"""
Per-network facts for the STD `networks[]` register items.

STD (0.13.0+) accepts `driver`, `ip_address`, `ipv6_address` and
`mac_address` on each network item, so its Ports page can handle macvlan /
ipvlan and host-network containers. Everything here is best effort and
validated locally: STD answers a 400 for the *whole* register when one of
these values is invalid, so anything that does not parse is left out.

The IP, IPv6 and MAC come from the container's own data. The driver is not
there; it is looked up once per network id (a network's driver never
changes) and cached.
"""

import ipaddress
import re
import threading

from logging_setup import get_logger

logger = get_logger("network_info")

MAX_DRIVER = 32  # STD's limit
_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")

# NetworkID -> driver name. Bounded; the oldest entry is evicted past the limit.
CACHE_MAX_ENTRIES = 256
_driver_cache = {}
_cache_lock = threading.Lock()

DETAIL_KEYS = ("driver", "ip_address", "ipv6_address", "mac_address")


def _clean_ip(value, version):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        addr = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    return str(addr) if addr.version == version else None


def _clean_mac(value):
    if isinstance(value, str) and _MAC_RE.match(value.strip()):
        return value.strip()
    return None


def _clean_driver(value):
    if isinstance(value, str) and value.strip() and len(value.strip()) <= MAX_DRIVER:
        return value.strip()
    return None


def _driver_for(client, network_id):
    if not network_id or client is None:
        return None
    with _cache_lock:
        if network_id in _driver_cache:
            return _driver_cache[network_id]
    try:
        driver = _clean_driver(client.networks.get(network_id).attrs.get("Driver"))
    except Exception as e:  # permissions, network removed, daemon hiccup
        logger.debug(f"Network driver lookup failed for {network_id[:12]}: {e}")
        return None
    if driver is not None:
        with _cache_lock:
            if len(_driver_cache) >= CACHE_MAX_ENTRIES:
                _driver_cache.pop(next(iter(_driver_cache)))
            _driver_cache[network_id] = driver
    return driver


def collect(container_attrs, client=None):
    """Build the `networks` list from a container's attrs.

    With `client` (a Docker client) each item also carries whichever of
    driver / ip_address / ipv6_address / mac_address Docker reported and
    that validate; without it items are just `{name, aliases}`.
    """
    network_settings = container_attrs.get("NetworkSettings") or {}
    networks_raw = network_settings.get("Networks") or {}
    out = []
    for name, data in networks_raw.items():
        is_dict = isinstance(data, dict)
        item = {"name": name, "aliases": (data.get("Aliases") or []) if is_dict else []}
        if client is not None and is_dict:
            details = {
                "driver": _driver_for(client, data.get("NetworkID")),
                "ip_address": _clean_ip(data.get("IPAddress"), 4),
                "ipv6_address": _clean_ip(data.get("GlobalIPv6Address"), 6),
                "mac_address": _clean_mac(data.get("MacAddress")),
            }
            item.update({k: v for k, v in details.items() if v is not None})
        out.append(item)
    return out
