---
description: Prepare a release — bump version, roll changelog, sync docs, validate, commit, push to dev, open PR
argument-hint: <version>   (e.g. 0.3.6)
---

<!--
Template from standards/release-prep-and-cut @ v1.1.0
(crzynet/homelab-configs/standards/release-prep-and-cut/README.md),
placeholders filled in for docker-api-notifier:

  `VERSION`             VERSION  (repo root; one bare-semver line)
  <VERSION_LITERAL>          the file's entire content, e.g. 0.4.2
  <README_BADGE_PATTERN>     none — the README has no version badge
  <README_WHATSNEW_SECTION>  none — the README has no What's New section
  <DOCS_TO_SYNC>             docs/PRD.md, CLAUDE.md, CHANGELOG.md footer links
  <LOCAL_CHECKS>             ruff, config validation, compose validation, image build
  <CHANGELOG_ARCHIVE_DIR>    docs/
-->

# Release Prep

You are preparing release **v$ARGUMENTS**. This command does ONLY the prep + PR
steps. It does **not** merge and does **not** create the GitHub release — the
human merges, and `/release-cut` (run after `main` CI is green) creates the
release.

## Execution rules

- Work on the `dev` branch. Never push directly to `main`.
- Do NOT add `Co-authored-by` lines to the commit.
- Do NOT create the GitHub release or tag in this command.
- If any validation step fails, STOP and report — do not commit broken state.
- Make exactly ONE commit covering version + changelog + all doc updates.
- `$ARGUMENTS` is the target version. It SHOULD be bare semver, no `v` prefix
  (e.g. `0.3.6`). If a leading `v` was typed (`v0.3.6`), strip it silently and
  proceed with the bare number. After stripping, if the value is empty or does
  not match `MAJOR.MINOR.PATCH` exactly (three integers, dot-separated, no
  pre-release/build suffix), STOP and ask for a valid version.
- Reminder on the `v` convention: the version is stored and used BARE
  everywhere (`VERSION`, changelog header, README badge, in-code image
  tags). The `v` prefix is added in exactly one place — the git tag / GitHub
  release — and that happens in `/release-cut`, not here.

## Step 0 — Preflight

1. Confirm the current branch is `dev`. If not, STOP and report.
2. Confirm the working tree is clean (`git status --porcelain` empty). If
   there are uncommitted changes, STOP and show them — the user must decide.
3. Read the current version from `VERSION`. Parse both the current
   version and `$ARGUMENTS` into `(MAJOR, MINOR, PATCH)` integer triples for
   comparison.

### 0a — Hard stops (never proceed past these)

- **Not newer.** If `$ARGUMENTS` is not strictly greater than the current
  version (compared as integer triples, not string compare), STOP and report.
  This blocks re-running an already-shipped version, going backward, or a typo
  that lands on an old number. Equal-to-current also stops.
- **Tag already exists.** Run `git fetch --tags` then check both
  `git tag -l "v$ARGUMENTS"` and `gh release view "v$ARGUMENTS"`. If either
  exists, STOP and report — the release already exists and must not be
  clobbered.

### 0b — Bump-tier classification (warn + confirm)

Classify the jump from current → target. Only a clean single-patch bump
proceeds silently; everything else pauses for explicit confirmation.

- **Patch bump** = MAJOR and MINOR unchanged, PATCH increased.
  - If PATCH increased by exactly 1 (e.g. `0.3.3` → `0.3.4`): proceed, no
    prompt.
  - If PATCH skipped ahead (e.g. `0.3.3` → `0.3.7`): WARN that N patch
    versions were skipped, show the expected next patch (current with
    PATCH+1), and require explicit confirmation before proceeding.

- **Minor bump** = MINOR increased (MAJOR unchanged), e.g. `0.3.3` → `0.4.0`.
  ALWAYS warn and require confirmation, even for the clean `.0` case. Message:
  this is a **new minor release**, which is infrequent — confirm it's
  intended. Note that a new minor also fires the changelog archive trigger
  (Step 3). If the target is a minor bump but PATCH is not `0` (e.g.
  `0.3.3` → `0.4.2`), additionally flag that new minors normally start at
  `.0`.

- **Major bump** = MAJOR increased, e.g. `0.3.3` → `1.0.0`. ALWAYS warn with
  strong language and require explicit confirmation: this is a **major
  release**, the rarest and most consequential bump, and it produces a new
  `:<major>` image tag. If MINOR or PATCH is not `0` (e.g. `1.2.0`),
  additionally flag that major releases normally start at `X.0.0`.

When warning, always show the three "expected next" successors from the
current version so the user can see what they may have meant:
next patch (`MAJOR.MINOR.PATCH+1`), next minor (`MAJOR.MINOR+1.0`),
next major (`MAJOR+1.0.0`).

Do not proceed on any warned tier without a clear affirmative ("yes",
"confirmed", etc.) in the chat. If the user declines, STOP.

### 0c — Remaining setup

4. Determine whether this is a **new minor/major** (MINOR or MAJOR differs from
   current) or a **patch within the current minor**. This decides whether the
   archive trigger fires (Step 3): minor and major bumps archive **every closed
   minor series** still in the active file; patch bumps archive nothing.
5. Capture today's date as `YYYY-MM-DD` for the changelog header.
6. **Cross-repo gate (STD wire contract).** Read the `[Unreleased]` entries.
   If any of them adds or renames a key this notifier sends to STD's
   `/api/v1/register` (see `CLAUDE.md` → Cross-Repo Coordination and
   `_to_canonical` in `notifiers/service_tracker_dashboard.py`), STOP and ask
   the user to confirm the STD release that accepts that key has already
   shipped, and which STD version it is. STD's validator rejects unknown keys,
   so the notifier must never lead the schema. Note the required STD version
   in the CHANGELOG entry.

## Step 1 — Bump the version

Overwrite `VERSION` so its entire content is `$ARGUMENTS` followed by a
newline (a single bare line, e.g. `0.4.3`). This is the single source of
truth: `main.py` reads it and logs the version at startup, and
`docker-publish.yml` fails a release whose tag (minus `v`) does not equal it.
Change nothing else.

## Step 2 — Roll the changelog

In `CHANGELOG.md`:

1. Change the `## [Unreleased]` header to `## [$ARGUMENTS] — <today>`.
2. Insert a fresh empty `## [Unreleased]` block (matching whatever HTML-comment
   skeleton the file already uses) directly above the new version header.
3. Leave the rolled section's entries exactly as written by the dev work — do
   not rewrite them, but DO sanity-check that every entry is user-facing prose
   and sits under a correct category heading (Added / Changed / Fixed /
   Security / Deprecated / Removed). Fix obvious miscategorisation only.
4. If the `[Unreleased]` section is empty (no entries to ship), STOP and
   report — there is nothing to release.
5. Update the compare links at the bottom of the file: point
   `[Unreleased]:` at `compare/v$ARGUMENTS...HEAD`, and add a
   `[$ARGUMENTS]: https://github.com/crzykidd/docker-api-notifier/compare/v<previous>...v$ARGUMENTS`
   line directly below it.

## Step 3 — Per-minor archive trigger (MINOR/MAJOR ONLY — summarize-on-archive)

Run this step only when Step 0 determined this is a **new minor (`0.x.0`) or
major (`x.0.0`) bump**. For a **patch release** (e.g. `0.3.6`), do NOT archive
anything — skip this step entirely.

Archive **every closed minor series** still living in the active `CHANGELOG.md`
(every series whose MINOR is below the new current minor), not just the
immediately-prior one — this clears any deferred backlog in one pass. For each
such closed series `<minor>.x`:

1. **Move the full detail to the archive.** Move the entire series (all its
   `## [<minor>.PATCH] — <date>` blocks, full content) out of `CHANGELOG.md` into
   `docs/CHANGELOG-<minor>.x.md`, newest-first, matching the
   format of any existing archive file. Full Keep-a-Changelog detail is preserved
   here.
2. **Leave a summary in the active file.** In place of each moved version, write a
   condensed summary block:
   - Heading: `## [<version>] — <date> (summary)`.
   - Body: **one bullet per major feature or fix.** Use judgment to **drop
     small/trivial entries** (typo fixes, copy tweaks, minor internal cleanups);
     keep user-visible features and significant fixes. Phrase each as a tight
     one-liner.
   - End the block with a deep link to the full archived section, e.g.
     `[Full notes →](docs/CHANGELOG-<minor>.x.md#<anchor>)`
     (anchor = the GitHub-style slug of the full header, e.g. `031--2026-06-21`).
3. Prepend a link to each new archive file in the "Archived releases" index at the
   bottom of `CHANGELOG.md` (create the index if absent).
4. Confirm the active `CHANGELOG.md` now holds `[Unreleased]` + the **current**
   minor series in **full detail** + each older minor as a **summary block** (with
   archive deep links).

## Step 4 — Sync the README

`README.md` has no version badge and no "What's New" section — release notes
live only in `CHANGELOG.md`. Only update content that already names a
specific version:

1. The "Semver-tagged images" example in `## Versioning & Releases`
   (e.g. `` `:0.4.2`, `:0` ``) → use `$ARGUMENTS` and its major.
2. Any top-of-file notice that names a specific version, if it is now stale.
3. Any env var, label, or interpreter table the `[Unreleased]` entries
   changed that the dev work did not already update (report it if so — the
   doc should have shipped with the code).

Do not add a badge or a What's New section.

## Step 5 — Sync long-form docs

- `docs/PRD.md`:
  - Add a Revision History row: the next number, today's date, and a
    one-line summary drawn from the changelog. Rows are in ascending order,
    so append at the BOTTOM of the table.
  - Bump the `## 5. Current State (v<old>)` heading to `v$ARGUMENTS` and add
    one sentence for this release to that section's first paragraph (the
    tag range `v0.1.0 → v<old>` becomes `v0.1.0 → v$ARGUMENTS`).
  - Adjust any other version-tagged annotation that already exists.
- `CLAUDE.md` Build Status — set "Current shipped release: **v$ARGUMENTS**"
  and rewrite the short paragraph under it to describe this release (and
  whether it changes the STD wire contract).

Do not invent new sections — only adjust version-referencing content that
already exists.

## Step 6 — Validate locally BEFORE committing

Run the same checks CI runs (`.github/workflows/ci.yml` plus the image build
in `docker-publish.yml`), from the repo root, in order:

1. **Lint** (ruff pinned to the version in `ci.yml`, currently 0.15.17):

   ```
   uvx ruff@0.15.17 check .
   ```

2. **Config validation** — runs the exact script from the `config-validate`
   job in `ci.yml`, so the two cannot drift. `uv run` supplies Python 3.11
   and `requirements.txt` (the script imports `interpreter_loader`):

   ```
   uv run --python 3.11 --with-requirements requirements.txt bash -c "$(python3 -c "import yaml; print(yaml.safe_load(open('.github/workflows/ci.yml'))['jobs']['config-validate']['steps'][-1]['run'])")"
   ```

3. **Compose validation** (unset-variable warnings are expected and fine):

   ```
   docker compose config --quiet
   ```

4. **Image build**, then confirm the image logs the new version at startup:

   ```
   docker build -t docker-api-notifier:release-check . && \
   docker run --rm --tmpfs /config -v /var/run/docker.sock:/var/run/docker.sock \
     docker-api-notifier:release-check timeout 5 python main.py 2>&1 | grep "version $ARGUMENTS"; \
   docker rmi docker-api-notifier:release-check
   ```

If ANY check fails, STOP, report exactly what failed, and do not commit.

Also grep for version-string drift: confirm no stale `<old-version>`
references remain in `README.md`, `VERSION`, `docs/PRD.md` §5, or the
`CLAUDE.md` Build Status block. Report any other occurrences you find rather
than blindly editing (historical CHANGELOG/PRD/HISTORY rows are expected).

## Step 7 — Commit

Stage `VERSION`, `CHANGELOG.md`, `README.md`, `docs/PRD.md`, `CLAUDE.md`
(and any `docs/CHANGELOG-*.x.md` archive files) by explicit path — never
`git add -A` — and make ONE commit. Template:

```
chore(release): prepare v$ARGUMENTS

- VERSION bumped to $ARGUMENTS
- CHANGELOG: rolled [Unreleased] → [$ARGUMENTS] — <today>, footer links
- README: <what changed, or "no version references to update">
- PRD: revision-history row + §5; CLAUDE.md: Build Status
<- archive line ONLY if a new-minor archive was performed>
```

No `Co-authored-by` lines.

## Step 8 — Push and open the PR

1. `git push origin dev`.
2. Open a PR `dev` → `main` with `gh pr create`:
   - Title: `Release v$ARGUMENTS`
   - Body: this release's CHANGELOG section (the `[$ARGUMENTS]` block you just
     rolled), so the PR description is the release notes. This is the same
     text `/release-cut` will use as the GitHub release body — single source
     of truth.
3. Capture the PR URL.

## Step 9 — Report and STOP

Print a short summary:

- The PR URL.
- Confirmation that local validation passed.
- The exact next steps for the human, verbatim:
  1. Review the PR on GitHub and wait for CI to go green.
  2. Merge the PR into `main`.
  3. Wait for the push-to-`main` build to publish `:latest` to the registry.
  4. Run `/release-cut $ARGUMENTS` to tag and publish the GitHub release.

Do NOT proceed past this point. Do not merge. Do not tag.
