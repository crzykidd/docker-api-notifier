---
name: 2026-11-22-healthz-ip-allowlist
status: completed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: HEALTH_ALLOWED_IPS allowlist implemented with tests and docs; ruff clean, 149 tests pass
---

# Task: Optional client-IP allowlist for /healthz (`HEALTH_ALLOWED_IPS`)

`/healthz` has no auth and has to be published on a host port so STD (on
another machine) can monitor the notifier. Add an optional allowlist: unset
means open to anyone (today's behaviour); set means only the listed clients
get the JSON, everyone else gets 403.

## Before you start

- Read `CLAUDE.md` (Definition of Done, code check-in), `standards.md`,
  `docs/PRD.md` §4 (env vars) and §4.2 (the endpoint), `health.py`
  (`_Handler`, `parse_port`, `start_from_env`), `healthcheck.py`, and
  `tests/test_health.py`.
- The working tree may contain other uncommitted work by the time you run.
  Only touch the files this task needs; don't revert or restage anything
  else.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Env var** `HEALTH_ALLOWED_IPS`: comma- and/or whitespace-separated list
   of IPv4/IPv6 addresses **or CIDR networks** (e.g.
   `10.100.18.10, 10.100.20.0/24, fd00::/8`). Parse with stdlib `ipaddress`
   (`ip_network(x, strict=False)`), once at server start (`start_from_env`),
   not per request.
   - Unset or empty → no filtering (log nothing extra).
   - Set → log one INFO line at startup listing the effective allowlist.
   - An entry that doesn't parse → WARNING naming it, and skip it. If *every*
     entry is invalid, **fail closed** (only loopback allowed) and log an
     ERROR saying so — a typo must not silently open the endpoint.
2. **Loopback is always allowed** (127.0.0.0/8 and ::1), so the image's
   `HEALTHCHECK` (`healthcheck.py`, which probes from inside the container)
   keeps working whatever the list says.
3. **Check in `_Handler`** for both GET and HEAD, using
   `self.client_address[0]`. Normalise IPv4-mapped IPv6
   (`::ffff:10.0.0.5` → `10.0.0.5`) before matching. Not allowed →
   `403` with a small JSON body `{"error": "forbidden"}` (HEAD: no body),
   before any snapshot work. Log denials at DEBUG only, rate-limited or
   not — never at INFO/WARNING (a scanner would flood the log).
   Unknown paths keep their current behaviour for allowed clients; for
   denied clients, 403 everything.
4. **Don't trust proxy headers** (`X-Forwarded-For` etc.); the filter is on
   the TCP peer. Say so in the README.
5. **Docs caveat** (README + PRD §4.2): the filter sees the address Docker
   delivers. With normal published ports (iptables DNAT) remote clients
   keep their real source IP. Clients connecting via the host's own
   loopback / docker-proxy may appear as the bridge gateway (e.g.
   172.x.0.1) — add that address if you probe from the host itself.
6. **Tests** in `tests/test_health.py` (existing style; real server on an
   ephemeral port is fine, as existing tests may already do):
   parsing (IPs, CIDRs, mixed separators, IPv6, invalid entries skipped,
   all-invalid → loopback only); allowed client → 200; denied → 403 for
   GET and HEAD with no snapshot call; loopback always allowed; unset →
   open; IPv4-mapped IPv6 normalisation (unit-test the matcher function).
   Lint `uvx ruff@0.15.17 check .` and
   `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`
   must both pass.
7. **docker-compose-example.yml**: in the notifier's `environment`, add
   `HEALTH_ALLOWED_IPS: ${HEALTH_ALLOWED_IPS:-}` and a line for it in the
   `.env` comment block at the top (e.g.
   `HEALTH_ALLOWED_IPS=10.100.18.10   # STD host; empty = anyone`). Update
   the `ports:` comment to mention it. Run
   `docker compose -f docker-compose-example.yml config --quiet`.

## Conventions to honor

- Definition of Done: CHANGELOG `[Unreleased]` → `### Added` (operator
  language); README env-var table row + the Health endpoint section; PRD §4
  env var + §4.2 + a revision-history row (append at the bottom).
- No new dependency (stdlib `ipaddress`). Health must never stop the
  notifier: a bad value degrades as above, never raises.
- Branch `dev`, prefix `feat:`, no `Co-authored-by:`.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git add` this file, then `git mv` it into `prompts/done/` (on success) or
   `prompts/failed/` (on failure).
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. You are a spawned agent: do **not** commit. Prepare the working tree, then report
   the file list + a proposed one-line commit message back to the orchestrating
   session. Never `git add -A`, never push.
