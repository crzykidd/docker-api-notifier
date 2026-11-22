from unittest import mock

import image_info

DIGEST = "ghcr.io/crzykidd/app@sha256:" + "a" * 64
IMG_ID = "sha256:" + "b" * 64


def _container(attrs, image_id=IMG_ID):
    container = mock.Mock()
    container.name = "web"
    container.attrs = {"Image": image_id}
    container.client.images.get.return_value = mock.Mock(attrs=attrs)
    return container


def test_full_payload():
    attrs = {
        "RepoDigests": [DIGEST],
        "Created": "2026-11-01T00:00:00Z",
        "Config": {"Labels": {
            "org.opencontainers.image.version": "1.2.3",
            "org.opencontainers.image.revision": "abc123",
            "org.opencontainers.image.source": "https://github.com/x/y",
        }},
    }
    assert image_info.build_image_info(attrs, IMG_ID) == {
        "id": IMG_ID,
        "repo_digests": [DIGEST],
        "created": "2026-11-01T00:00:00Z",
        "version": "1.2.3",
        "revision": "abc123",
        "source": "https://github.com/x/y",
    }


def test_partial_no_labels_empty_digests_local_build():
    out = image_info.build_image_info(
        {"RepoDigests": [], "Created": "2026-01-01T00:00:00Z", "Config": {"Labels": None}},
        IMG_ID,
    )
    assert out == {"id": IMG_ID, "created": "2026-01-01T00:00:00Z"}


def test_missing_everything_keeps_only_id():
    assert image_info.build_image_info({}, IMG_ID) == {"id": IMG_ID}


def test_bad_digest_items_dropped():
    attrs = {"RepoDigests": [DIGEST, "nodigest", "a b@sha256:" + "a" * 64,
                             "repo@sha256:short", "repo@sha256:" + "A" * 64]}
    assert image_info.build_image_info(attrs, IMG_ID)["repo_digests"] == [DIGEST]


def test_repo_digests_capped_at_20():
    digests = [f"repo{i}@sha256:" + "a" * 64 for i in range(30)]
    out = image_info.build_image_info({"RepoDigests": digests}, IMG_ID)
    assert out["repo_digests"] == digests[:20]


def test_truncation():
    attrs = {
        "Created": "c" * 100,
        "Config": {"Labels": {
            "org.opencontainers.image.version": "v" * 200,
            "org.opencontainers.image.revision": "r" * 200,
            "org.opencontainers.image.source": "s" * 600,
        }},
    }
    out = image_info.build_image_info(attrs, IMG_ID)
    assert len(out["created"]) == 64
    assert len(out["version"]) == 128
    assert len(out["revision"]) == 128
    assert len(out["source"]) == 512


def test_lookup_resolves_by_image_id_not_tag():
    container = _container({"RepoDigests": [DIGEST]})
    container.attrs["Config"] = {"Image": "app:latest"}
    info = image_info.lookup(container)
    container.client.images.get.assert_called_once_with(IMG_ID)
    assert info["repo_digests"] == [DIGEST]


def test_lookup_caches_by_image_id():
    container = _container({"RepoDigests": [DIGEST]})
    image_info.lookup(container)
    image_info.lookup(container)
    assert container.client.images.get.call_count == 1


def test_lookup_failure_returns_none_and_is_not_cached():
    container = _container({})
    container.client.images.get.side_effect = RuntimeError("pruned")
    assert image_info.lookup(container) is None
    assert image_info.lookup(container) is None
    assert container.client.images.get.call_count == 2


def test_lookup_without_image_id():
    container = _container({})
    container.attrs = {}
    assert image_info.lookup(container) is None


def test_cache_is_bounded(monkeypatch):
    monkeypatch.setattr(image_info, "CACHE_MAX_ENTRIES", 3)
    for i in range(10):
        image_info.lookup(_container({}, image_id=f"sha256:{i}"))
    assert len(image_info._cache) <= 3
