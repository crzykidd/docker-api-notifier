---
name: 2026-11-22-socket-proxy-permission-warnings
status: completed        # pending | completed | failed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: docker_access.py shared module; 403 warn-once-per-transition + 10 min back-off for network and image lookups; /healthz docker_permissions; README socket-proxy section; tests; lint+pytest green
---

# Task: Say clearly when a Docker socket proxy blocks the network or image lookups

Lands before the 0.6.0 release, on `dev`.

**Found live on 2026-11-22.** Both crzynet hosts run the notifier behind
`tecnativa/docker-socket-proxy` with only `CONTAINERS=1 EVENTS=1 PING=1 VERSION=1 INFO=1`.
With `NETWORKS=0` and `IMAGES=0`, the proxy answers **403 Forbidden** to these two
lookups:
- **`client.networks.get(<id>)`**, the per-network driver lookup added in
  `network_info._driver_for` (0.6.0 dev). It fails and logs **only at debug**, so the
  networks reach STD with IPs but no `driver`. STD then can't recognise macvlan/ipvlan,
  and Home Assistant never showed on STD's Ports page.
- **`client.images.get(<id>)`**, the `image_info` lookup (0.5.0). It logs a warning
  per image ("Could not look up image … registering without image_info: 403 …"),
  but the warning never says *why* or what to change. So STD's image-digest check has had
  no data on either host since 0.5.0.

The operator fix is `NETWORKS=1` and `IMAGES=1` on the proxy. Both are read-only while
`POST=0`. The notifier should **say that plainly**, and the README should list the
settings it needs.

## Before you start

- Read `CLAUDE.md`, `network_info.py`, `image_info.py` (`lookup`, ~L79-110, and its
  first-warning logic), `health.py` (`/healthz`) and the README sections on running
  behind a socket proxy, if there are any; there may be none.
- Note `docker.errors.APIError` and its `.status_code` / `response.status_code` (403).
  The tecnativa body is `"Request forbidden by administrative rules"`.

## Review corrections (2026-11-22) — these override "What to do" where they conflict

1. **One shared module, not two copies.** Put the 403 detection, the back-off state and
   the ok/denied/unknown status for both lookups in one small module (e.g.
   `docker_access.py`). `network_info._driver_for` and `image_info.lookup` call it;
   `health.snapshot()` reads its status for `docker_permissions`. Match **exactly 403**:
   `isinstance(exc, docker.errors.APIError) and exc.status_code == 403`
   (`docker.errors.NotFound` is an `APIError` subclass for 404 — that is a normal "network
   removed" case and must stay at debug).
2. **Warn on the transition to denied, not once per process.** A later success clears
   the flag and logs once at INFO ("Docker network lookups allowed again"), so a proxy
   that is fixed and later broken again warns again. Per-lookup repeats stay at debug.
3. **Thread safety.** The refresh thread and the event loop both run these lookups:
   guard the denied/back-off state with a lock (as the existing caches do).
4. **`/healthz` "unknown".** A kind stays `"unknown"` until its lookup has run at least
   once — e.g. STD not configured, the feature not advertised by STD, or opted out
   (`STD_SEND_IMAGE_INFO` / `STD_SEND_NETWORK_DETAILS=false`). Say so in the README field
   notes.
5. **README proxy snippet.** The notifier gets `DOCKER_HOST=tcp://<proxy-service>:2375`
   and **no** `/var/run/docker.sock` mount; only the proxy mounts the socket (`:ro`).
   Keep the notifier's other mounts (`/config`, `/etc/hostname:/etc/host_hostname:ro` if
   the existing README example uses it) as the current example has them.
6. Skip the Home Assistant narrative in docs/CHANGELOG; describe the behavior generally.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Recognise a proxy refusal:** add one small helper, e.g. `docker_permission_denied(exc)`,
   that is True for a 403 from the Docker API.
2. **Network driver lookup** (`network_info._driver_for`):
   - **On a 403:** log **one WARNING per process**: "Docker refused the network lookup
     (403). If the notifier runs behind a docker-socket-proxy, set NETWORKS=1 on it (it
     stays read-only with POST=0); without it STD cannot recognise macvlan, ipvlan or
     host networks."
   - **After that,** don't retry each network on every refresh. Cache "denied" for a
     while, e.g. 10 minutes, then try again, so fixing the proxy takes effect without a
     restart.
   - **Other errors** stay at debug, as today.
3. **Image lookup** (`image_info.lookup`):
   - **On a 403:** log one WARNING per process naming `IMAGES=1` in the same way, and
     stop the per-image warning spam for 403s. Other errors keep today's behavior.
   - Apply the same back-off as the network lookup.
4. **`/healthz`:** add a `docker_permissions` object, e.g.
   `{"networks": "ok"|"denied"|"unknown", "images": "ok"|"denied"|"unknown"}`.
   - It shows the latest outcome of each lookup.
   - A denial doesn't make the notifier unhealthy; it's informational, like a STD
     outage.
   - Update the README `/healthz` example.
5. **README:** add a "Running behind a docker-socket-proxy" section.
   - The required settings are `CONTAINERS=1`, `EVENTS=1`, `NETWORKS=1` (the network
     details for STD 0.13.0+) and `IMAGES=1` (`image_info`, for STD's image update
     check). `PING=1` / `VERSION=1` / `INFO=1` are harmless.
   - Keep `POST=0`: the notifier never writes.
   - Give a compose snippet with the proxy service.
   - Say what breaks when `NETWORKS` or `IMAGES` is 0.
6. **Tests:**
   - one WARNING for repeated 403s;
   - other errors still at debug;
   - the back-off, then a retry;
   - the `/healthz` field;
   - the image path's 403 handling;
   - no per-image warning spam on 403.
7. **Docs, all in the same commit:**
   - **CHANGELOG `[Unreleased]`:** under Changed or Fixed, in operator words. Example:
     "A Docker socket proxy that blocks network or image lookups is now reported once,
     with the setting to change (`NETWORKS=1`, `IMAGES=1`); before, network details
     were silently missing and image lookups logged a 403 per image."
   - **`docs/PRD.md`:** a revision row.
   - **`docs/decisions.md`:** the one-warning-plus-back-off choice.
8. **Verify:** this repo's lint and tests are green.

## Conventions to honor

- No change to what is sent to STD. This is diagnostics and docs only.
- Commit prefix `fix:`. No `Co-authored-by:` trailers.

## When done

1. Update this file's frontmatter: `status`, `completed`, `result`.
2. Move this file into `prompts/done/` (success) or `prompts/failed/`. Use a plain `mv`
   if it's untracked.
3. Hand off ONE commit: this prompt file, the files you changed, and the prompt move.
   - **If you are a spawned agent:** don't commit; report the file list + message.
   - **If you are running directly:** ask `commit these as "<message>"? (y/n)`. On `y`,
     stage those paths and commit on `dev`.
   - Never `git add -A`, never push.
