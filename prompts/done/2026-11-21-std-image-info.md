---
name: 2026-11-21-std-image-info
status: completed        # pending | completed | failed
created: 2026-11-21
model: sonnet
completed: 2026-11-21
result: image_info sent to STD 0.12.0+ gated on /api/v1/meta; retry 5xx-only, 10s timeouts, pytest suite + CI Test job; working tree prepared, uncommitted
---

# Task: send `image_info` (the running image) to STD, gated on STD's `/api/v1/meta` (notifier 0.5.0)

STD 0.12.0 adds an image update check. For moving tags (`latest`, `stable`, `16`) it
compares the registry's current digest with the digest the container actually runs.
Only the notifier knows the running digest. This task makes the STD notifier send an
optional `image_info` object on `/api/v1/register`.

The field must be sent **only when the STD it talks to accepts it**. STD's schema uses
`extra="forbid"`, so an older STD would reject every register with a 400.

The target release is **notifier 0.5.0**. It pairs with STD 0.12.0+, and STD ships
first, per the cross-repo ordering rule: consumer leads, producer follows.

## Before you start

- **This repo was brought up to the crzynet standards after this prompt was written.**
  Read the current `CLAUDE.md` and `standards.md`. Where they differ from the
  conventions below (branching, commit and PR flow, the handoff-prompt workflow, CI,
  the release process, where decisions are recorded), **the repo's current rules win**.
- Read `docs/PRD.md` (the STD wire contract, env vars).
- **Check STD's current contract before you start.** This prompt matches STD API
  revision 5 as of 2026-11-21. Re-read STD's `api_version.py` (`API_REVISION`,
  `API_REVISION_HISTORY`, `FEATURES`) and `docs/register-api.md` on STD's `main` or
  `dev`. If anything later than revision 5 touches register, cover it too or flag it.
- Code to read:
  - `notifiers/service_tracker_dashboard.py`: `_to_canonical()`, `register()` and
    `post_with_retry()`;
  - `main.py`: `handle_container_event()`, where `image_name` comes from
    `container.attrs["Config"]["Image"]`, plus the `_extract_*` helpers and
    `periodic_update_loop()`.
- **STD's contract is the source of truth.** STD 0.12.0 is released (tag `v0.12.0`).
  Read it from the STD repo (`crzykidd/service-tracker-dashboard`, `main`, or the local
  clone at `~/projects/service-tracker-dashboard`):
  - `docs/register-api.md` → "The running image (`image_info`, API revision 5)";
  - `schemas.py` → `class ImageInfo`;
  - design rationale: `docs/design/2026-11-21-image-update-check.md` §2.3 and §8.

## The contract (copied from STD `schemas.py`, API revision 5; verify against the source)

```python
class ImageInfo(BaseModel):            # extra="forbid": unknown keys are a 400
    id: Optional[str]            # local image id "sha256:<hex>", max 100 chars
    repo_digests: Optional[List[str]]  # Docker's raw RepoDigests, max 20 items,
                                 # each must match  ^[^@\s]{1,255}@sha256:[0-9a-f]{64}$
    created: Optional[str]       # image Created (ISO 8601), max 64
    version: Optional[str]       # label org.opencontainers.image.version, max 128
    revision: Optional[str]      # label org.opencontainers.image.revision, max 128
    source: Optional[str]        # label org.opencontainers.image.source, max 512 (STD keeps http(s) only)

# RegisterPayload.image_info: Optional[ImageInfo] = None
```

How STD reads the field:

| Payload | Meaning |
|---|---|
| `image_info` absent or `null` | "no update": STD keeps the stored values |
| `image_info: {...}` | replaces the stored values; a field left out is cleared |
| `image_name` changed and no `image_info` | STD clears the stored digest |

STD picks the `RepoDigests` item that matches the entry's repository, so send them
**raw**. Don't filter or normalize.

## Verified facts and decisions (added by the planning session, 2026-11-21)

These were checked against STD `origin/dev` and on this host. Trust them over the
"verify" wording above, but still re-read STD's `api_version.py` in case it moved past
revision 5.

**Verified against STD source**

- `API_REVISION` is still **5**; `FEATURES` includes `"image_info"`; `ImageInfo` matches
  the contract block above exactly. STD tag `v0.12.0` exists, so the ordering rule is met.
- `GET /api/v1/meta` (no auth, `routes_mgmt_api.py` `meta()`) returns
  `{"std_version": str, "api_revision": int, "features": [str, ...]}`. STD older than
  0.10.0 has no `/meta` and answers **404**: treat 404 / connection error / bad JSON as
  "no `image_info` support".
- `X-STD-API-Revision` and `X-STD-Version` are set on **every** `/api/` response,
  errors included (`app.py` `_api_revision_headers`).
- A rejected register is **HTTP 400** (not 422), body
  `{"error": "Invalid register payload", "details": [pydantic errors], "unknown_keys": [...]}`.
  Detect an `image_info` rejection structurally: `"image_info" in body.get("unknown_keys", [])`
  **or** any `details[i]["loc"][0] == "image_info"` (a malformed digest). Don't string-match
  the error text. `CLAUDE.md` says "HTTP 422" in the Cross-Repo Coordination section; that
  is stale, so fix it to 400 as part of this task.

**Verified on this host (Docker 29.9.3, containerd image store)**

- `images.get(<id>).attrs["RepoDigests"]` is populated on the containerd store, e.g.
  `['ghcr.io/crzykidd/docker-api-notifier@sha256:5e6b…']`, and the image id equals that
  index digest. So "prefer `RepoDigests`" works on both stores; there's no special
  containerd path needed. Note this in `docs/decisions.md`. OCI labels
  (`org.opencontainers.image.version/revision/source`) are present on GHCR-built images.

**Decisions (made by the user)**

1. **Retry policy, both notifiers:** don't retry 4xx. Change `retry.py` so it retries
   connection errors, timeouts, and **5xx** `HTTPError`s only; a 4xx raises immediately.
   This is what makes the STD "400 → retry once without `image_info`" fallback fast. Update
   the README "How It Works" retry paragraph (it currently says DNS retries 4xx) and the
   PRD wherever the retry policy is described.
2. **HTTP timeouts, both notifiers:** every outbound `requests` call (STD register, STD
   `/meta`, Technitium DNS) passes a timeout. Put one shared constant in `retry.py`
   (e.g. `REQUEST_TIMEOUT_SECONDS = 10`) and use it at each call site. No new env var.
   Today a hung downstream blocks the event loop forever.
3. **Add a test suite:** `pytest` in a new `requirements-dev.txt` (pin it), tests under
   `tests/`, and a `Test` job in `.github/workflows/ci.yml` (job `name: Test`, running
   `pip install -r requirements-dev.txt && pytest -q`). Tests must not need a Docker daemon
   or `/config`: fake the Docker client and the HTTP layer (`unittest.mock` is fine, no extra
   dependency needed), and set `logging_setup._configured = True` in `conftest.py` the same
   way `ci.yml`'s config validation does. Cover retry/timeout behavior too (4xx not retried,
   5xx retried). Update `standards.md` (the code-checkin row: drop "Exempt: test suite",
   say a `Test` job exists) and `CLAUDE.md` (CI section). **Don't** touch the GitHub
   ruleset: the orchestrating session adds `Test` as a required check after CI reports it.
   Add `Test` to `/release-prep`'s Step 6 local checks in `.claude/commands/release-prep.md`
   (`uv run --python 3.11 --with-requirements requirements-dev.txt pytest -q`).

**Design requirements the prompt didn't state**

- **Thread safety:** the refresh loop thread and the event loop both call STD `register()`.
  Guard the cached `/meta` state (features, revision, version, logged-once flags) with a
  `threading.Lock`.
- **Cache image facts by image id.** An image id's facts never change. Keep a small dict
  (bounded, e.g. evict when it passes ~256 entries) so the refresh loop doesn't call
  `images.get` for every container every cycle. A failed lookup is not cached.
- **Keep the gate state readable** (e.g. a small `std_status()` function in the STD
  notifier returning `std_version`, `api_revision`, `image_info_supported`, last-check time).
  A follow-up prompt (`/healthz`) will report it.
- **Don't break DNS:** `image_info` is built only when STD dispatch fires, and the DNS
  notifier must never receive it.

## Working tree check

Run `git status --porcelain` and cross-reference the files this plan touches. If any
have uncommitted changes, list them and ask before you touch them. Work on `dev`.

## What to do

1. **Resolve the running image by id, not by tag.**
   - Look it up with `client.images.get(container.attrs["Image"])`. That is the image id
     the container was created from.
   - **Don't** use `images.get(Config.Image)`: after `docker compose pull` without a
     recreate, the tag already points at the new image while the container still runs
     the old one.
   - Fields to build:
     - `id` is the image id;
     - `repo_digests` is `image.attrs["RepoDigests"]`, capped at 20, with any item that
       doesn't match the regex dropped;
     - `created` is `image.attrs["Created"]`;
     - `version`, `revision` and `source` come from
       `image.attrs["Config"]["Labels"]`, using the three OCI keys. Truncate each to its
       maximum length.
   - Omit `None` values and empty lists.
   - **Never let the lookup break a register.** Image not found (pruned), a permission
     error or a timeout means you send the register **without** `image_info` and log at
     debug or warning level, rate-limited.
   - **Containerd image store** (the Docker Engine 29 default for new installs):
     `RepoDigests` is still present. If it is empty and the image id is itself an index
     digest, check what makes sense. Prefer `RepoDigests`, and verify on both stores if
     you can; if you can't, document it.
   - Local builds have empty `RepoDigests`. That's fine: send the other fields, and STD
     shows "local image".
2. **Gate on STD's capability.**
   - `GET <STD_URL>/api/v1/meta` needs no auth. It returns `features` (a list) and the
     API revision. Confirm the exact response shape against STD's `routes_mgmt_api.py`
     `meta()`.
   - Send `image_info` only when `features` contains `"image_info"`.
   - Cache the answer:
     - check at startup and on the first register;
     - re-check when the `X-STD-API-Revision` response header on a register response
       differs from the cached revision. STD sends this header, plus `X-STD-Version`,
       on every `/api/` response, errors included, so a separate timer isn't needed;
     - re-check after a register 400 that mentions `image_info`, then retry once without
       the field.
   - If `/meta` is unreachable or has no `image_info`, omit the field and **log once**,
     not on every register: "STD at <url> does not accept image_info (API revision N);
     upgrade STD to 0.12.0+ for image digest checks."
   - **Log STD's API revision and version once at startup,** from `/api/v1/meta`, and
     again when the `X-STD-API-Revision` / `X-STD-Version` headers change. STD has sent
     these since 0.10.0 (API revision 2), and the notifier doesn't read them yet. This
     also closes STD's parked FUTURE item "Notifier logging STD's API revision".
3. **Wire it into the STD payload only.** Add `image_info` to whatever `_to_canonical()`
   / the allowed-keys list uses. The Technitium DNS notifier must not see or need it.
   The periodic update loop sends it too, so STD gets fresh digests after a recreate.
4. **Opt-out env var**, e.g. `STD_SEND_IMAGE_INFO` (default true). Some operators may
   not want image digests sent. Document it in the README env table.
5. **Tests.**
   - If the repo has a test suite, add tests for:
     - payload building: full, partial, no labels, empty `RepoDigests`, a bad digest
       item dropped, truncation;
     - the gate: features with and without `image_info`, `/meta` down, the
       revision-change re-check, the 400 fallback;
     - the lookup failing → register still sent without the field.
   - If there's no suite, add a minimal pytest setup for the new pure functions, and
     note it in CHANGELOG/HISTORY as tooling.
   - Run whatever lint or CI the repo has.

## Validation before handing off

Run every check `/release-prep` runs (see `.claude/commands/release-prep.md` Step 6):
ruff (`uvx ruff@0.15.17 check .`), config validation, compose validation, the image build,
and the new `pytest -q`. Also start the built image against the local Docker socket with
no STD configured and confirm it boots cleanly (no tracebacks; DNS-only behavior unchanged).
Report the results.

## Conventions to honor

- **CHANGELOG `[Unreleased]` → Added:** "Sends the running image (digests and OCI
  labels) to Service Tracker Dashboard 0.12.0+ for its image update check; only when STD
  advertises support; opt out with `STD_SEND_IMAGE_INFO=false`. Logs STD's API revision
  at startup."
- **PRD:** the STD wire contract section, env vars, the pairing table
  (notifier 0.5.0 ↔ STD 0.12.0+), and the revision-history bump.
- **README:** the env var, plus a note on the pairing.
- **Commits:** prefix `feat:`. No `Co-authored-by:` trailers. Work on `dev`; never push
  to `main`.
- **Release order:** STD 0.12.0 is already released, so the ordering rule is met. The
  pairing docs should say "STD 0.12.0+".

## When done

1. Update this file's frontmatter: set `status` (completed/failed), `completed` (the
   date), and `result` (one line).
2. `git mv` this file into `prompts/done/` (on success) or `prompts/failed/` (on
   failure). Create the subdirectory if it doesn't exist yet. If the file is untracked, a
   plain `mv` is fine.
3. Record any non-obvious decisions in `docs/decisions.md`, newest at top.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move. Present the file list and a one-line message (e.g.
   `feat: send the running image (image_info) to STD 0.12.0+, gated on /api/v1/meta`).
   - **If you are a spawned agent:** do **not** commit. Prepare the working tree, then
     report the file list and the proposed message back to the orchestrating session.
   - **If you are running directly:** ask the user `commit these as "<message>"? (y/n)`.
     On `y`, stage those specific paths and commit on `dev`.

   Either way: never `git add -A`, never push, never auto-commit, and no
   `Co-authored-by:`.
