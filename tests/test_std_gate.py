import json
from unittest import mock

import pytest
import requests

from notifiers import service_tracker_dashboard as std

INFO = {"id": "sha256:" + "b" * 64}


def _resp(status=200, body=None, headers=None):
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body if body is not None else {}).encode()
    r.headers.update(headers or {})
    return r


def _meta(features, revision=5, version="0.12.0"):
    return _resp(200, {"std_version": version, "api_revision": revision,
                       "features": features})


@pytest.fixture
def http(monkeypatch):
    """Fake the HTTP layer: .get serves /meta, .post serves /register."""
    h = mock.Mock()
    h.get.return_value = _meta(["register", "image_info"])
    h.post.return_value = _resp(200, {}, {"X-STD-API-Revision": "5",
                                          "X-STD-Version": "0.12.0"})
    monkeypatch.setattr(std.requests, "get", h.get)
    monkeypatch.setattr(std.requests, "post", h.post)
    return h


def _register(**extra):
    std.register(container_name="web", docker_host="h", **extra)


def _sent_payloads(http):
    return [c.kwargs["json"] for c in http.post.call_args_list]


def test_sent_when_features_include_image_info(http):
    _register(image_info=INFO)
    assert _sent_payloads(http)[0]["image_info"] == INFO


def test_omitted_when_features_lack_image_info(http):
    http.get.return_value = _meta(["register"], revision=3, version="0.10.0")
    _register(image_info=INFO)
    assert "image_info" not in _sent_payloads(http)[0]
    assert std.std_status()["image_info_supported"] is False


def test_omitted_when_meta_404(http):
    http.get.return_value = _resp(404)
    _register(image_info=INFO)
    assert "image_info" not in _sent_payloads(http)[0]


def test_omitted_when_meta_unreachable_or_bad_json(http):
    http.get.side_effect = requests.ConnectionError()
    assert std.image_info_supported() is False
    http.get.side_effect = None
    bad = _resp(200)
    bad._content = b"not json"
    http.get.return_value = bad
    std._state["last_check"] = 0  # past the retry window
    assert std.image_info_supported() is False


def test_unsupported_is_logged_once(http, caplog):
    http.get.return_value = _meta(["register"], revision=3)
    with caplog.at_level("INFO"):
        for _ in range(3):
            std.refresh_meta()
    msgs = [r.message for r in caplog.records if "does not accept image_info" in r.message]
    assert len(msgs) == 1
    assert "API revision 3" in msgs[0] and "0.12.0+" in msgs[0]


def test_meta_checked_once_then_cached(http):
    for _ in range(3):
        _register(image_info=INFO)
    assert http.get.call_count == 1


def test_failed_meta_is_retried_only_after_window(http):
    http.get.side_effect = requests.ConnectionError()
    std.image_info_supported()
    std.image_info_supported()
    assert http.get.call_count == 1
    std._state["last_check"] -= std.META_RETRY_SECONDS + 1
    std.image_info_supported()
    assert http.get.call_count == 2


def test_startup_logs_version_and_revision(http, caplog):
    with caplog.at_level("INFO"):
        std.check_meta_at_startup()
    assert any("version 0.12.0, API revision 5" in r.message for r in caplog.records)


def test_revision_header_change_triggers_recheck(http):
    http.get.return_value = _meta(["register"], revision=4)
    std.image_info_supported()
    assert http.get.call_count == 1
    # STD upgraded: the register response now carries revision 5.
    http.get.return_value = _meta(["register", "image_info"], revision=5)
    _register(image_info=INFO)  # gate still says no, this one omits it
    assert "image_info" not in _sent_payloads(http)[0]
    assert http.get.call_count == 2
    assert std.std_status()["image_info_supported"] is True
    _register(image_info=INFO)
    assert _sent_payloads(http)[1]["image_info"] == INFO


def test_same_revision_header_does_not_recheck(http):
    _register(image_info=INFO)
    _register(image_info=INFO)
    assert http.get.call_count == 1


def test_400_unknown_keys_retries_once_without_image_info(http):
    http.post.side_effect = [
        _resp(400, {"error": "Invalid register payload", "details": [],
                    "unknown_keys": ["image_info"]}),
        _resp(200),
    ]
    # First /meta advertises image_info; the re-check after the 400 does not.
    http.get.side_effect = [_meta(["register", "image_info"]), _meta(["register"])]
    _register(image_info=INFO)
    sent = _sent_payloads(http)
    assert len(sent) == 2
    assert "image_info" in sent[0] and "image_info" not in sent[1]
    assert std.std_status()["image_info_supported"] is False


def test_400_bad_digest_detail_retries_without_image_info(http):
    http.post.side_effect = [
        _resp(400, {"error": "Invalid register payload", "unknown_keys": [],
                    "details": [{"loc": ["image_info", "repo_digests", 0]}]}),
        _resp(200),
    ]
    _register(image_info=INFO)
    sent = _sent_payloads(http)
    assert len(sent) == 2 and "image_info" not in sent[1]


def test_rejection_sticks_while_std_still_claims_support(http):
    http.post.side_effect = [
        _resp(400, {"unknown_keys": ["image_info"], "details": []}),
        _resp(200, {}, {"X-STD-API-Revision": "5"}),
        _resp(200, {}, {"X-STD-API-Revision": "5"}),
    ]
    _register(image_info=INFO)   # meta still advertises image_info
    _register(image_info=INFO)
    assert "image_info" not in _sent_payloads(http)[2]


def test_400_for_other_reasons_is_not_retried(http):
    http.post.side_effect = [_resp(400, {"unknown_keys": ["bogus"], "details": []})]
    _register(image_info=INFO)
    assert http.post.call_count == 1


def test_401_is_not_retried(http):
    http.post.side_effect = [_resp(401)]
    _register()
    assert http.post.call_count == 1


def test_5xx_is_retried(http):
    http.post.side_effect = [_resp(503), _resp(200)]
    _register()
    assert http.post.call_count == 2


def test_register_passes_timeout(http):
    _register()
    assert http.post.call_args.kwargs["timeout"] > 0
    assert http.get.call_args.kwargs["timeout"] > 0 if http.get.called else True


def test_no_image_info_means_field_absent(http):
    _register()
    assert "image_info" not in _sent_payloads(http)[0]


# --- network_details gate -------------------------------------------------

NET_FULL = [{"name": "lan", "aliases": ["a"], "driver": "macvlan",
             "ip_address": "192.168.1.50", "ipv6_address": "fd00::2",
             "mac_address": "02:42:ac:11:00:02"}]
NET_PLAIN = [{"name": "lan", "aliases": ["a"]}]

# What a real STD <= API revision 5 answers for networks[0].driver: only
# "networks" in unknown_keys, the real culprit in details[].loc.
OLD_STD_400 = {
    "error": "Invalid register payload",
    "unknown_keys": ["networks"],
    "details": [{"loc": ["networks", 0, "driver"], "type": "extra_forbidden",
                 "msg": "Extra inputs are not permitted"}],
}


def test_per_feature_support_from_meta(http):
    http.get.return_value = _meta(["register", "image_info", "network_details"], 6, "0.13.0")
    assert std.feature_supported("network_details") is True
    assert std.feature_supported("image_info") is True
    assert std.std_status()["features_supported"] == {
        "image_info": True, "network_details": True}
    http.get.return_value = _meta(["register", "image_info"])
    std.refresh_meta()
    assert std.feature_supported("network_details") is False
    assert std.image_info_supported() is True
    with pytest.raises(ValueError):
        std.feature_supported("nope")


def test_features_supported_is_null_before_first_check(http):
    assert std.std_status()["features_supported"] == {
        "image_info": None, "network_details": None}


def test_network_details_sent_when_advertised(http):
    http.get.return_value = _meta(["register", "network_details"], 6, "0.13.0")
    _register(networks=NET_FULL)
    assert _sent_payloads(http)[0]["networks"] == NET_FULL


def test_network_details_reduced_when_unsupported(http):
    _register(networks=NET_FULL)  # default /meta: no network_details
    assert _sent_payloads(http)[0]["networks"] == NET_PLAIN


def test_network_details_unsupported_logged_once(http, caplog):
    with caplog.at_level("INFO"):
        for _ in range(3):
            std.refresh_meta()
    msgs = [r.message for r in caplog.records if "does not accept network_details" in r.message]
    assert len(msgs) == 1 and "0.13.0+" in msgs[0] and "API revision 5" in msgs[0]


def test_opt_out_env_reduces_networks(http, monkeypatch):
    http.get.return_value = _meta(["register", "network_details"], 6)
    monkeypatch.setenv("STD_SEND_NETWORK_DETAILS", "false")
    _register(networks=NET_FULL)
    assert _sent_payloads(http)[0]["networks"] == NET_PLAIN


def test_400_old_std_body_retries_with_stripped_networks_keeping_image_info(http):
    http.get.return_value = _meta(["register", "image_info", "network_details"], 6)
    http.post.side_effect = [_resp(400, OLD_STD_400), _resp(200)]
    _register(networks=NET_FULL, image_info=INFO)
    first, second = _sent_payloads(http)
    assert first["networks"] == NET_FULL
    assert second["networks"] == NET_PLAIN          # never dropped, just reduced
    assert second["image_info"] == INFO
    assert std.std_status()["features_supported"]["network_details"] is False


def test_400_unknown_keys_networks_alone_is_not_acted_on(http):
    http.get.return_value = _meta(["register", "network_details"], 6)
    http.post.side_effect = [_resp(400, {"unknown_keys": ["networks"], "details": []})]
    _register(networks=NET_FULL)
    assert http.post.call_count == 1


def test_400_validator_error_on_new_std_also_blames_network_details(http):
    http.get.return_value = _meta(["register", "network_details"], 6)
    http.post.side_effect = [
        _resp(400, {"unknown_keys": [],
                    "details": [{"loc": ["networks", 1, "ip_address"],
                                 "type": "value_error"}]}),
        _resp(200),
    ]
    _register(networks=NET_FULL)
    assert _sent_payloads(http)[1]["networks"] == NET_PLAIN


def test_400_blaming_both_features_strips_both(http):
    http.get.return_value = _meta(["register", "image_info", "network_details"], 6)
    body = {"unknown_keys": ["image_info", "networks"],
            "details": [{"loc": ["networks", 0, "mac_address"]}]}
    http.post.side_effect = [_resp(400, body), _resp(200)]
    _register(networks=NET_FULL, image_info=INFO)
    second = _sent_payloads(http)[1]
    assert "image_info" not in second and second["networks"] == NET_PLAIN


def test_network_details_rejection_sticks_while_std_claims_support(http):
    http.get.return_value = _meta(["register", "network_details"], 6)
    http.post.side_effect = [
        _resp(400, OLD_STD_400),
        _resp(200, {}, {"X-STD-API-Revision": "6"}),
        _resp(200, {}, {"X-STD-API-Revision": "6"}),
    ]
    _register(networks=NET_FULL)
    _register(networks=NET_FULL)
    assert _sent_payloads(http)[2]["networks"] == NET_PLAIN


def test_revision_header_change_rechecks_for_network_details(http):
    http.get.return_value = _meta(["register"], 5)
    _register(networks=NET_FULL)  # reduced; response header says revision 5
    http.post.return_value = _resp(200, {}, {"X-STD-API-Revision": "6"})
    _register(networks=NET_FULL)  # reduced again, but header 6 triggers recheck
    http.get.return_value = _meta(["register", "network_details"], 6)
    _register(networks=NET_FULL)
    assert _sent_payloads(http)[1]["networks"] == NET_PLAIN
    # recheck happened on the 2nd response; the 3rd register sees the new answer
    assert std.feature_supported("network_details") is True


# --- label coercion in _to_canonical --------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("1", True), ("YES", True), ("on", True),
    ("false", False), ("0", False), ("No", False), ("off", False),
])
def test_bool_label_values(raw, expected):
    out = std._to_canonical({"container_name": "web", "docker_host": "h",
                             "internal.health": raw})
    assert out["internal_health_check_enabled"] is expected


def test_bool_typo_leaves_key_out_and_warns(caplog):
    with caplog.at_level("WARNING"):
        out = std._to_canonical({"container_name": "web", "docker_host": "h",
                                 "external.health": "ture"})
    assert "external_health_check_enabled" not in out
    assert any("web" in r.message and "external.health" in r.message
               for r in caplog.records)


def test_bad_int_dropped_with_warning(caplog):
    with caplog.at_level("WARNING"):
        out = std._to_canonical({"container_name": "web", "docker_host": "h",
                                 "sort.priority": "high"})
    assert "sort_priority" not in out
    assert any("sort_priority" in r.message for r in caplog.records)


def test_skip_key_is_not_in_payload():
    out = std._to_canonical({"container_name": "web", "docker_host": "h", "skip": "true"})
    assert "skip" not in out
