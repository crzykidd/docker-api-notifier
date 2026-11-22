# Decisions

Non-obvious decisions — approach changes, rejected alternatives,
workarounds — newest at top. One entry per decision.

---

## 2026-11-21 — /healthz: downstream outages never make it unhealthy

- **200 vs 503 depends only on the notifier itself**: the Docker daemon
  answers a `ping()` (cached ~15 s so probes don't hammer the socket) and
  the event loop, once started, hasn't stopped. A STD or Technitium outage
  shows only in that notifier's `last_error*` / `error_count` and keeps
  HTTP 200; otherwise an autoheal setup would restart-loop the notifier
  over someone else's outage.
- **Stdlib `ThreadingHTTPServer` in a daemon thread**, started in `main()`
  before the boot scan; no new dependency. A bind failure logs an error and
  the notifier runs without the endpoint (health must never stop
  notifying). `HEALTH_PORT=0` disables it and the image's `HEALTHCHECK`
  (`healthcheck.py`) then exits 0.
- **Separate Docker client for health pings**, so a probe never shares the
  blocking event-stream connection.
- **Error strings are scrubbed, not just truncated.** `requests` exceptions
  embed the full URL and the DNS token travels in its query string, so
  `health.sanitize_error()` cuts query strings and userinfo, masks
  `token=`-style values and any configured secret, then truncates to 200
  chars. The DNS failure log line uses the same scrubber (it used to print
  the raw exception, token included; fixed right after this change).
- **Notifier outcomes are recorded inside each `register()`** (final result
  after retries), keeping the public `register(**kwargs)` contract
  unchanged. `health.py` imports the STD module lazily in `snapshot()`
  because the notifiers import `health` (avoids a cycle).

---

## 2026-11-21 — image_info: gate on /meta, resolve by id, retry only 5xx

- **Gate on STD's `/api/v1/meta`, not a version guess.** STD's schema is
  `extra="forbid"`, so an unsupported `image_info` would 400 every
  register. The notifier caches `features` from the unauthenticated
  `/meta` (lock-guarded: the refresh thread and event loop both
  register), re-checks on an `X-STD-API-Revision` header change or a
  register 400 that blames `image_info` (detected structurally via
  `unknown_keys` / `details[].loc[0]`, never by error text), and retries
  that register once without the field. A rejection is remembered per
  API revision so an STD that advertises the feature but still rejects it
  is not re-sent the field every cycle. Failed `/meta` checks are retried
  at most every 5 minutes (or sooner when a revision header shows up).
- **Resolve the image by `container.attrs["Image"]` (id), not
  `Config.Image` (tag).** After `docker compose pull` without a recreate
  the tag points at the new image while the container runs the old one.
- **No containerd special case.** Verified on Docker 29.9.3 with the
  containerd image store: `images.get(id).attrs["RepoDigests"]` is
  populated (e.g. `ghcr.io/crzykidd/docker-api-notifier@sha256:...`) and
  the image id equals that index digest, so "send `RepoDigests` raw"
  works on both stores. Local builds have empty `RepoDigests`; the other
  fields still go out. Not verified on the classic overlay2 store here.
- **Facts cached by image id** (bounded, ~256 entries): an id's facts never
  change, so the refresh loop does not call `images.get` per container per
  cycle. Failed lookups are not cached and warn once per image id.
- **Retry only connection errors, timeouts and 5xx** (both notifiers); a
  4xx is a definitive answer. This also makes the 400 fallback instant.
  Reverses the v0.3.0 note that DNS retried 4xx. Every outbound request
  passes `retry.REQUEST_TIMEOUT_SECONDS` (10 s), no env var.
- **Test suite added** (`pytest`, `tests/`, CI `Test` job), reversing the
  adoption-time "no test job" exemption. The ruleset still needs `Test`
  added as a required check once CI reports it (done by the orchestrating
  session, not this change).
- **Stale doc fixed:** `CLAUDE.md` and the README said STD rejects
  unknown keys with HTTP 422; STD answers 400.

---

## 2026-11-21 — CodeQL required to run, not to be clean

The `main` ruleset's `code_scanning` rule uses `alerts_threshold: none`
and `security_alerts_threshold: none`, so a PR needs a completed CodeQL
analysis but isn't blocked by its findings. That is what
`code-checkin-and-pr` @ 1.2.0 specifies ("the gate is that the scan
ran"). STD's ruleset blocks on errors / high-or-higher instead; tightening
here later is a one-field change if findings start getting ignored.

---

## 2026-11-21 — Standards adoption: what was adapted, and why

Adopted `handoff-prompt-workflow` @ 2.0.0, `code-checkin-and-pr` @ 1.2.0,
and `release-prep-and-cut` @ 1.1.0, modeled on STD's adoption (2026-11-15).

- **Done in-session, not via a handoff prompt.** The adoption is what
  introduces `prompts/`; there was no queue to put it in. Work after this
  commit follows the threshold rule.
- **Root `VERSION` file** (bare semver), same as STD, not a `version.py` —
  the Dockerfile already copies the repo root to `/app`, so `main.py` reads
  `VERSION` beside itself and logs it at startup. Missing file logs
  `unknown` rather than crashing.
- **CI is push-only** (`dev`/`main`), no `pull_request` trigger, copying
  STD's fix for duplicate same-named check runs stalling required checks.
- **No migration check, no test job.** No database; no tests yet (the
  standard exempts a repo with no suite). Adding tests is still an open
  question in PRD §10.
- **Config validation also runs the real interpreter loader** over
  `interpreters/builtin/` and `docs/community-interpreters/`, not just a
  YAML parse — a structurally valid YAML can still be rejected by the
  loader and silently skipped at runtime. It sets
  `logging_setup._configured = True` before import so the loader's logger
  doesn't try to open `/config/notifier.log` on the runner. Rejected:
  adding a log-path env var just for CI.
- **Release commands adapted from the templates, not copied from STD.**
  STD's carry MCP-version, migration, badge and What's New steps that don't
  exist here. This repo's README has no badge/What's New, so Step 4 only
  touches existing version references. Added a project step: a cross-repo
  gate that stops prep if `[Unreleased]` adds an STD wire key, enforcing
  the "STD ships the schema first" rule.
- **ruff 0.15.17 with STD's rule set** (E, W, F, I, B; E501 ignored). The
  only findings were import order and two unused imports.
- **Retention copied from STD** (GHCR via `GITHUB_TOKEN`; untagged
  versions never deleted because multi-arch manifests reference them).
