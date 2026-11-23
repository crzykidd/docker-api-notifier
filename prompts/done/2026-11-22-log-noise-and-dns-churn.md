---
name: 2026-11-22-log-noise-and-dns-churn
status: completed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: Dispatch logs deduped, short DNS INFO line + status!=ok failure, refresh loop sleeps first, unchanged CNAMEs skipped; 125 tests pass
---

# Task: Cut duplicate/verbose log lines, stop the startup double-register, and skip unchanged DNS records

Production logs on a real host (em-dockha01, `:dev`, 2026-11-22) showed four
problems. All of them are pre-existing behaviour, not regressions:

1. **Every notifier dispatch is logged twice.** `main.py` logs
   `STD notifier triggered for homeassistant on start` and then
   `notifiers/service_tracker_dashboard.py` logs
   `STD notifier triggered for "homeassistant" on "start"`. DNS does the same
   (`main.py:230` and `notifiers/technitium_dns.py:43`).
2. **The full Technitium JSON reply is logged at INFO** on every DNS update
   (`notifiers/technitium_dns.py:64`, ~600 chars per line).
3. **Every container is registered twice at startup.** The boot scan in
   `main()` finishes, then `periodic_update_loop` (thread started right
   after) runs its first pass immediately, ~0.2 s later, re-registering
   everything to STD. Its `time.sleep` is at the *end* of the loop.
4. **Every DNS update bumps the zone's SOA serial** (245 → 251 in one
   session), even when the CNAME already points at the same target, because
   the notifier always calls `records/add` with `overwrite=true`. That causes
   needless zone transfers to secondaries.

## Before you start

- Read `CLAUDE.md` (Definition of Done, code check-in rules), `standards.md`,
  and `docs/PRD.md` §3.3 (notifier module contract) plus any PRD section
  that documents the DNS notifier, the refresh loop or logging.
- Read `main.py` (`handle_container_event`, `periodic_update_loop`, `main`),
  `notifiers/technitium_dns.py`, `notifiers/service_tracker_dashboard.py`
  (`register`), `health.py` (`record_refresh`, `snapshot`), `retry.py`, and
  the tests under `tests/` (they fake Docker and HTTP; `conftest.py`).
- Technitium HTTP API reference:
  https://github.com/TechnitiumSoftware/DnsServer/blob/master/APIDOCS.md
  (sections "Add Record" and "Get Records"). Confirm the `records/get`
  parameters and response shape from that doc before writing the check —
  don't guess. Expected shape is roughly
  `{"status":"ok","response":{"zone":{...},"records":[{"name","type","ttl","rData":{"cname": "..."},...}]}}`.
- `DNS_SERVER_URL` is the **full add endpoint** (e.g.
  `http://10.100.16.16:5380/api/zones/records/add`), and the API token
  travels in the query string. Any log line or error that could include a
  URL or exception must go through `health.sanitize_error()` — see the
  existing failure path and `test_dns_failure_log_line_has_no_token`.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **One dispatch line per notifier per event.** Keep exactly one INFO line
   per notifier per event. Keep the `main.py` ones (they sit next to the
   `[MATCH]` line) and demote the module-level
   `... triggered for "<name>" on/due to "<action>"` lines in both notifiers
   to DEBUG (don't delete them: a module called without `main.py` still
   logs at debug). Don't change any other log levels.
2. **DNS result as one short INFO line.** Replace the raw-body INFO line
   with a one-liner such as
   `DNS record <fqdn> CNAME <value>: added` (or `updated`, whatever the
   reply actually supports), and log the full `response.text` at DEBUG.
   If Technitium answers HTTP 200 with `"status"` other than `"ok"`
   (its API does this for errors), treat it as a failure: log an ERROR with
   the `errorMessage` (sanitized), and `health.record_error("dns", ...)`
   instead of `record_success`. Check whether that's already handled; it
   appears not to be.
3. **No startup double-register.** Make `periodic_update_loop` sleep
   `STD_REFRESH_SECONDS` *before* its first pass (the boot scan already
   reported everything). Keep the per-container try/except and
   `health.record_refresh()`. `/healthz` `refresh_loop.last_run_at` will be
   `null` until the first refresh — confirm nothing (health status, tests,
   README `/healthz` example) treats that as unhealthy, and note it in the
   README's `/healthz` field description if one exists.
4. **Skip unchanged DNS records.** Before `records/add`, look the record up
   with Technitium's `records/get` for the same `domain`/`zone`. If a CNAME
   for that name already exists with the same target (compare
   case-insensitively and ignore a trailing dot) **and** the same TTL,
   skip the add: log at DEBUG (`DNS record <fqdn> already points at
   <value>; unchanged`), and call `health.record_success("dns")` (an
   unchanged record is a success). Otherwise add as today.
   - Derive the get URL from `DNS_SERVER_URL` by replacing a trailing
     `/records/add` with `/records/get`. If the URL doesn't end that way,
     skip the check and add as today (log once at DEBUG why).
   - The lookup is best-effort: on any error (connection, timeout, non-200,
     `status != "ok"`, unexpected shape), fall back to the add. Don't let
     the lookup's failure become a DNS error in `/healthz`. Use the same
     timeout (`REQUEST_TIMEOUT_SECONDS`); don't wrap the lookup in the
     retry decorator (a failed lookup just falls through to the add, which
     retries).
   - Accepted side effect: when skipped, the record's comment keeps its
     older "Added by ... at <timestamp>" text. Record that in decisions.md.
   - Never log the lookup URL or raw exception (token in query string).
5. **Tests** (in `tests/`, matching existing style, no real network):
   - one INFO dispatch line per notifier per event (use `caplog`);
   - the DNS INFO line doesn't contain the raw JSON; `status:"error"` reply
     → ERROR + `record_error`;
   - refresh loop sleeps before its first pass (patch `time.sleep` to raise
     after the first call and assert no container was handled);
   - DNS skip when existing CNAME matches (no `records/add` call,
     `record_success`), add when target differs, add when TTL differs, add
     when the lookup errors, add (no lookup) when the URL doesn't end in
     `/records/add`;
   - no token in any log line on the lookup failure path.
   Run lint `uvx ruff@0.15.17 check .` and the suite
   `uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`.
   Both must pass.

## Conventions to honor

- Definition of Done: CHANGELOG `[Unreleased]` entries (operator-facing
  language; `### Changed` for the log and refresh changes, `### Fixed` for
  the SOA churn and the 200-with-error case), README if operator-visible
  behaviour is documented there (refresh timing, `/healthz`, DNS notifier
  behaviour, log examples), PRD reviewed and updated with a revision row if
  it documents any of this — otherwise say "PRD reviewed, no change needed".
- Don't change the STD wire contract or the `register(**kwargs)` contract.
- Keep changes minimal and in the existing style; no new dependencies.
- Branch is `dev`. Commit prefix `fix:`; no `Co-authored-by:`.

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdir if it doesn't exist yet. (The file is untracked, so
   `git add` it first, then `git mv`.)
3. Record any non-obvious decisions in the project's `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move (the prompt is **not** pre-committed — it bundles in here). Present
   the file list and a one-line message summarising the changes.
   - **You are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list + proposed message back to the orchestrating session.
   Never `git add -A` (beyond the prompt file itself), never push, never auto-commit.
