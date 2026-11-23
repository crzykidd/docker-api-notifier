import os
import sys

# Make the repo root importable (main.py, retry.py, notifiers/ live there).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Skip logging_setup's /config/notifier.log handler (not writable here);
# same trick as the config-validate job in ci.yml.
import logging_setup  # noqa: E402

logging_setup._configured = True

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    """Reset module-level caches and make retries instant for every test."""
    import docker_access
    import health
    import image_info
    from notifiers import service_tracker_dashboard as std

    docker_access.reset()
    health.reset()
    image_info._cache.clear()
    image_info._warned.clear()
    import network_info
    network_info._driver_cache.clear()
    with std._state_lock:
        std._state.update(
            std_version=None, api_revision=None, features=None,
            image_info_supported=False, network_details_supported=False,
            last_check=None, last_check_ok=False, rejected={},
        )
        std._flags.clear()
    monkeypatch.setattr(std.post_with_retry.retry, "sleep", lambda s: None)
    monkeypatch.setenv("STD_URL", "http://std.test")
    monkeypatch.setenv("STD_API_TOKEN", "tok")
