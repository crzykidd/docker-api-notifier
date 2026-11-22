"""Docker HEALTHCHECK probe: exit 0 when /healthz answers 200, else 1.

The slim image has no curl or wget, so this uses urllib. With
HEALTH_PORT=0 (endpoint disabled) it exits 0 so the container is not
marked unhealthy. Standalone on purpose: no project imports, so it never
touches the log file.
"""

import os
import sys
import urllib.request

raw = os.environ.get("HEALTH_PORT", "8080").strip() or "8080"
try:
    port = int(raw)
except ValueError:
    port = 8080  # same fallback as the server

if port == 0:
    sys.exit(0)

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=4) as r:
        sys.exit(0 if r.status == 200 else 1)
except Exception:
    sys.exit(1)
