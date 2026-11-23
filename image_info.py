"""
Running-image facts for the STD `image_info` register field.

STD (0.12.0+) compares the registry's current digest for a moving tag
with the digest the container actually runs. Only the notifier can see
the running digest, so it resolves the image the container was created
from (by image id, never by tag) and reports its digests and OCI labels.

Everything here is best effort: a failed lookup returns None and the
register goes out without `image_info`.
"""

import re
import threading

import docker_access
from logging_setup import get_logger

logger = get_logger("image_info")

# STD's ImageInfo limits (API revision 5). Longer values are truncated.
MAX_ID = 100
MAX_REPO_DIGESTS = 20
MAX_CREATED = 64
MAX_VERSION = 128
MAX_REVISION = 128
MAX_SOURCE = 512

_DIGEST_RE = re.compile(r"^[^@\s]{1,255}@sha256:[0-9a-f]{64}$")

_LABEL_FIELDS = (
    ("version", "org.opencontainers.image.version", MAX_VERSION),
    ("revision", "org.opencontainers.image.revision", MAX_REVISION),
    ("source", "org.opencontainers.image.source", MAX_SOURCE),
)

# An image id's facts never change, so cache them. Bounded; the oldest
# entry is evicted past the limit.
CACHE_MAX_ENTRIES = 256
_cache = {}
_cache_lock = threading.Lock()

# Image ids whose lookup failure was already logged at warning level, so a
# pruned image does not warn on every refresh cycle.
_warned = set()


def build_image_info(attrs, image_id):
    """Build the STD `image_info` dict from `images.get(...).attrs`.

    `None` values and empty lists are omitted. `RepoDigests` is sent raw
    (STD picks the entry matching the repository), minus items that would
    fail STD's validation.
    """
    out = {}
    if isinstance(image_id, str) and image_id and len(image_id) <= MAX_ID:
        out["id"] = image_id

    digests = []
    for item in attrs.get("RepoDigests") or []:
        if isinstance(item, str) and _DIGEST_RE.match(item):
            digests.append(item)
        else:
            logger.debug(f"Dropping malformed RepoDigests item {item!r}")
    if digests:
        out["repo_digests"] = digests[:MAX_REPO_DIGESTS]

    created = attrs.get("Created")
    if isinstance(created, str) and created:
        out["created"] = created[:MAX_CREATED]

    labels = (attrs.get("Config") or {}).get("Labels") or {}
    for field, key, limit in _LABEL_FIELDS:
        value = labels.get(key)
        if isinstance(value, str) and value:
            out[field] = value[:limit]
    return out


def lookup(container):
    """Return image_info for the image `container` was created from, or None.

    Resolves by `container.attrs["Image"]` (the image id), not by
    `Config.Image`: after a pull without a recreate the tag points at the
    new image while the container still runs the old one.
    """
    image_id = (container.attrs or {}).get("Image")
    if not image_id:
        return None

    with _cache_lock:
        cached = _cache.get(image_id)
    if cached is not None:
        return _copy(cached)

    if docker_access.should_skip("images"):
        return None
    try:
        image = container.client.images.get(image_id)
        info = build_image_info(image.attrs or {}, image_id)
    except Exception as e:
        if docker_access.is_denied_error(e):
            # One warning on the transition (naming IMAGES=1), then debug only.
            docker_access.record_denied("images")
            logger.debug(f"Image lookup refused for {container.name}: {e}")
            return None
        with _cache_lock:
            first = image_id not in _warned
            _warned.add(image_id)
            if len(_warned) > CACHE_MAX_ENTRIES:
                _warned.clear()
        log = logger.warning if first else logger.debug
        log(
            f"Could not look up image {image_id} for {container.name}; "
            f"registering without image_info: {e}"
        )
        return None

    docker_access.record_ok("images")
    with _cache_lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            _cache.pop(next(iter(_cache)))
        _cache[image_id] = info
    return _copy(info)


def _copy(info):
    out = dict(info)
    if "repo_digests" in out:
        out["repo_digests"] = list(out["repo_digests"])
    return out
