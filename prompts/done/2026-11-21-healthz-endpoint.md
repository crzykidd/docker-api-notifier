---
name: 2026-11-21-healthz-endpoint
status: completed        # pending | completed | failed
created: 2026-11-21
model: sonnet            # opus = research/planning, sonnet = coding
completed: 2026-11-21     # filled when the work is done
result: "/healthz endpoint + Docker HEALTHCHECK added (health.py, healthcheck.py); 66 tests pass"
---

# Task: add a `/healthz` HTTP endpoint (version, uptime, Docker and notifier status)

Operators currently have no way to see a running notifier's state except by reading its
logs. Add a small HTTP endpoint that reports the version, uptime, and the state of the
Docker connection and each notifier, and wire it into a Docker `HEALTHCHECK`. This ships
in **notifier 0.5.0** alongside the `image_info` work.

## Before you start

- Read `CLAUDE.md` and `standards.md`. The repo's current rules win over anything here.
- Read `docs/PRD.md` §3 (architecture, module responsibilities, event flow) and §4
  (configuration model), and `README.md` (env var tables, "How It Works").
- **This runs after `prompts/done/2026-11-21-std-image-info.md`.** That task added: a
  `pytest` suite under `tests/` (with a `conftest.py` that sets
  `logging_setup._configured = True`), a `Test` CI job, a shared
  `REQUEST_TIMEOUT_SECONDS` in `retry.py`, and a readable STD gate state in
  `notifiers/service_tracker_dashboard.py` (something like `std_status()`, returning
  `std_version`, `api_revision`, `image_info_supported`, and the last check time). Read
  what actually landed and build on it. If that prompt isn't in `prompts/done/`, STOP and
  report.
- Code to read: `main.py` (`main()`, `periodic_update_loop()`, `handle_container_event()`,
  `get_version()`, `get_host_name()`), both notifiers' `register()`, `logging_setup.py`,
  and the `Dockerfile`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## Design (decided by the planning session — follow it, record deviations)

**Server**

- Use the standard library only: `http.server.ThreadingHTTPServer` plus a
  `BaseHTTPRequestHandler`, run in a daemon thread started early in `main()`, before the
  boot scan, so the endpoint answers while a slow boot scan is running. No new runtime
  dependency.
- New env var **`HEALTH_PORT`**, default `8080`. `HEALTH_PORT=0` disables the server.
  A non-integer value logs a warning and falls back to the default. Bind `0.0.0.0`
  (inside the container).
- Routes: `GET /healthz` → JSON. Anything else → 404 with a small JSON body. `HEAD
  /healthz` is optional.
- Send the handler's request logging to the shared logger at **debug** level. The default
  `BaseHTTPRequestHandler.log_message` writes every request to stderr, and a 30-second
  Docker healthcheck would flood the log.
- If the port can't be bound (in use), log an error and keep running without the
  endpoint. Health is an add-on and must never stop notifying.

**Response body** (all timestamps are ISO 8601 UTC; durations in integer seconds)

```json
{
  "status": "ok",
  "version": "0.5.0",
  "started_at": "2026-11-21T22:00:00Z",
  "uptime_seconds": 3600,
  "host": "<docker_host used for DNS/STD>",
  "docker": {
    "connected": true,
    "server_version": "29.9.3",
    "last_event_at": "…",
    "events_seen": 123
  },
  "refresh_loop": {"enabled": true, "interval_seconds": 60, "last_run_at": "…"},
  "interpreters": ["dockflare", "traefik"],
  "notifiers": {
    "dns": {
      "configured": true,
      "last_success_at": "…", "last_error_at": null, "last_error": null,
      "success_count": 10, "error_count": 0
    },
    "service_tracker_dashboard": {
      "configured": true,
      "std_version": "0.12.0", "api_revision": 5, "image_info_supported": true,
      "last_success_at": "…", "last_error_at": null, "last_error": null,
      "success_count": 40, "error_count": 0
    }
  }
}
```

- **Never include secrets**: no tokens, no full URLs with credentials, no env dump. A
  short error string (exception class plus a truncated message, ≤200 characters) is fine.
  Make sure it can't echo a token, for example from a URL in an exception message.
- `configured` reflects the env vars (DNS: `DNS_SERVER_URL` and `DNS_SERVER_API_TOKEN`;
  STD: the existing `is_configured()`), not whether any container opted in.
- The STD block's revision, version and `image_info_supported` fields come from the gate
  state the `image_info` task added. Use `null` until the first `/meta` check.

**Health semantics**

- `status: "ok"` + HTTP **200** when the notifier itself is working: the Docker daemon
  answers a `ping()`, and (once `main()` reaches it) the event loop is running.
  Rate-limit the ping: cache the result for ~15 s so frequent probes don't hammer the
  socket.
- `status: "unhealthy"` + HTTP **503** when Docker is unreachable.
- **Downstream failures (STD or Technitium down) do not make it unhealthy.** They show up
  in the per-notifier fields but keep HTTP 200. Otherwise an autoheal setup would
  restart-loop the notifier over someone else's outage. Record this in `docs/decisions.md`.

**State tracking**

- Add a small module (e.g. `health.py`) that holds the counters and timestamps behind a
  `threading.Lock`, with tiny recorder functions such as `record_event()`,
  `record_refresh()`, `record_success(notifier)` and `record_error(notifier, exc)`, plus
  `snapshot()` to build the JSON. The event loop, the refresh thread and the HTTP thread
  all touch it.
- Call the recorders from `main.py` (events, refresh loop) and from each notifier's
  `register()` on its final outcome: after retries, success or failure.
- Keep the notifiers' public `register(**kwargs)` contract unchanged (PRD §3.3). Update
  `notifiers/_template.py` to show the recorder calls so new notifiers pick them up.

**Docker image**

- `Dockerfile`: `EXPOSE 8080`, plus a `HEALTHCHECK` that probes
  `http://127.0.0.1:${HEALTH_PORT:-8080}/healthz` with Python's `urllib`. The slim image
  has no curl or wget. When `HEALTH_PORT=0`, the healthcheck must exit 0 (healthy), so
  turning off the endpoint doesn't make the container unhealthy. Suggested timing:
  `--interval=30s --timeout=5s --start-period=30s --retries=3`. Put the probe in a tiny
  script (e.g. `healthcheck.py`) rather than a long inline `python -c`.
- `docker-compose.yml` and the README compose example: show an optional, commented-out
  `ports: - "8080:8080"` mapping for reaching `/healthz` from the host. Don't publish it
  by default.

## What to do

1. Add `health.py` (state + snapshot + HTTP server) as described.
2. Wire the recorders into `main.py` and both notifiers, and start the server in `main()`.
3. Add `healthcheck.py` and the `Dockerfile` `EXPOSE` / `HEALTHCHECK`.
4. **Tests** (in the existing `tests/`, no Docker daemon needed):
   - the snapshot shape and values;
   - 200 vs 503 (fake `ping()` succeeding or failing);
   - downstream errors keep 200;
   - no secret appears in the snapshot (set fake tokens in the env and assert they are
     absent from the JSON);
   - `HEALTH_PORT` parsing (default, `0`, garbage);
   - the 404 route;
   - the server answering on an ephemeral port (bind port `0` in the test, read back the
     real port).
5. **Docs:**
   - `README`: a `HEALTH_PORT` row in the General env table; a short "Health endpoint"
     section with the example JSON and the 200/503 semantics; the compose example.
   - `PRD`: §3 architecture/module responsibilities (the new `health.py` and HTTP
     thread), §4 configuration (the env var), and a revision-history row.
   - `CHANGELOG [Unreleased]` → Added: "A `/healthz` HTTP endpoint (port 8080, set
     `HEALTH_PORT=0` to disable) reports the version, uptime, the Docker connection, and
     each notifier's last success/error; the image now has a Docker `HEALTHCHECK`. A STD
     or DNS outage doesn't mark the notifier unhealthy."
   - `CLAUDE.md`: mention `health.py` where the Stack and module conventions live.
6. **Validate** with every `/release-prep` Step 6 check: ruff, config validation, compose
   validation, the image build, and `pytest -q`. Then run the built image against the
   local Docker socket with `-p 18080:8080`, no STD and no DNS configured, and confirm:
   - `curl -s localhost:18080/healthz` returns 200 with sane JSON;
   - `docker inspect --format '{{.State.Health.Status}}'` reaches `healthy`;
   - `HEALTH_PORT=0` boots with no listener and a still-healthy healthcheck.

   Report the actual output.

## Conventions to honor

- Commits use the `feat:` prefix, with no `Co-authored-by:` trailers. Work on `dev`.
- No STD wire-contract change: this task must not touch `_to_canonical()` or the payload.
- Docs ship in the same commit as the code (CLAUDE.md Definition of Done). In your report,
  say explicitly that you reviewed the PRD.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdir if it doesn't exist yet. If the file is untracked, a plain
   `mv` is fine.
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session, which
     surfaces the `y/n` to the user.
   - **If you are running directly (manual fallback):** ask the user
     `commit these as "<message>"? (y/n)` yourself. On `y`, stage those specific paths
     and commit on the current branch.
   Either way: never `git add -A`, never push, never auto-commit, and no
   `Co-authored-by:`.
