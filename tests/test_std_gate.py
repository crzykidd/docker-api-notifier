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
