---
name: 2026-11-22-std-network-details-and-label-hardening
status: completed        # pending | completed | failed
created: 2026-11-22
model: sonnet
completed: 2026-11-22
result: network_info.py + per-feature STD gate (network_details), label hardening, std.skip; docs updated; lint and 106 tests green
---

# Task: Send network details to STD 0.13.0+, generalize the STD feature gate, harden `dockernotifier.std.*` labels, add `dockernotifier.std.skip`

Target release: **notifier 0.6.0**. It's a minor, because it adds features.

Service Tracker Dashboard (STD) **0.13.0** shipped on 2026-11-22. Its Ports page now
understands three cases:
- **macvlan / ipvlan** containers, which have their own LAN address, so every port they
  listen on is reachable there without being published;
- **host-network** containers, whose ports are bound straight on the host;
- the per-network **driver, IPv4, IPv6 and MAC**, also shown in STD's entry details.

STD accepts these as new optional keys on each `networks` item, and advertises them with
the feature **`network_details`** in `GET /api/v1/meta`. This task makes the notifier
send them, but only to an STD that advertises the feature. STD has shipped first, as the
ordering rule requires; the notifier follows.

It also fixes three label bugs found in a code review (see
`~/projects/service-tracker-dashboard/docs/design/2026-11-22-notifier-labels.md` §4), and
adds a notifier-only opt-out label.

## Before you start

- Read this repo's `CLAUDE.md` (Definition of Done, Cross-Repo Coordination, Notifier
  Module Conventions) and `standards.md`.
- **Read the 0.5.0 `image_info` gate. It is the pattern to generalize:**
  - `notifiers/service_tracker_dashboard.py`: `_state`, `refresh_meta`,
    `image_info_supported`, `_observe_headers`, `_is_image_info_rejection` and
    `_post_register`;
  - its tests in `tests/test_std_gate.py`;
  - the label handling in `main.py`: `handle_container_event` (~L230-252),
    `_extract_networks` (~L130) and the `base_kwargs` dict (~L197).
- **STD's side of the contract (read only; don't edit that repo):**
  - `~/projects/service-tracker-dashboard/schemas.py` `NetworkMembership`;
  - `~/projects/service-tracker-dashboard/docs/register-api.md`;
  - STD PRD §5.3 and §25.

### The wire shape STD 0.13.0 accepts

Each `networks` item allows these keys, and only these (`extra="forbid"`):

```json
{"name": "lan_macvlan",
 "aliases": [],
 "driver": "macvlan",
 "ip_address": "192.168.1.50",
 "ipv6_address": "fd00::2",
 "mac_address": "02:42:ac:11:00:02"}
```

- **`driver`:** optional str. STD lowercases it, allows at most 32 characters, and
  accepts any value (`bridge`, `macvlan`, `ipvlan`, `host`, `overlay`, `none`, plugin
  names).
- **`ip_address`:** optional IPv4. **`ipv6_address`:** optional IPv6. STD canonicalizes
  both.
- **`mac_address`:** optional. STD normalizes it.
- **Empty values:** `""`, `null` or an absent key all mean "not reported".
  **Prefer leaving the key out.**
- **Invalid values:** an invalid or wrong-family IP, an invalid MAC, or a driver over 32
  characters gets a **400 for the whole register**. Never send anything you didn't read
  from Docker, and validate locally before sending (see step 2).
- **Older notifiers:** leaving out all four keeps the old behavior.

## Review corrections (2026-11-22) — these override "What to do" where they conflict

1. **How STD reports a nested unknown key.** STD builds `unknown_keys` from `loc[0]`
   only (`~/projects/service-tracker-dashboard/routes_api.py` ~L421). An older STD
   (API revision ≤5, `NetworkMembership` is `extra="forbid"` with only name/aliases)
   that receives `networks[0].driver` answers `unknown_keys: ["networks"]` plus a
   `details` item with `loc: ["networks", 0, "driver"]`, `type: "extra_forbidden"`.
   - Detect `network_details` **only from `details[].loc`**: `loc[0] == "networks"`,
     `len(loc) >= 3`, and `loc[2]` is one of `driver` / `ip_address` /
     `ipv6_address` / `mac_address` (any error type: extra_forbidden on old STD, a
     validator error on new STD).
   - **Never act on `"networks"` in `unknown_keys`**, and never drop the `networks`
     field: the stripped retry keeps every item's `name` and `aliases`.
   - Add a test with exactly that old-STD response body.
2. **The gate lives in the STD notifier, not in `main.py`.** `base_kwargs` is shared by
   DNS and STD. `main.py` collects the full per-network details; the STD module
   (`register` / `_to_canonical` / `_post_register`) reduces each item to
   `{name, aliases}` when `network_details` is unsupported, rejected, or opted out
   (`STD_SEND_NETWORK_DETAILS=false`). Same single owner for the 400 retry. DNS ignores
   `networks` as today.
3. **Driver lookup client and cost.** Use `container.client.networks.get(NetworkID)`
   (`main.py` creates several clients: ~L96, ~L274, ~L290). Module-level bounded cache
   keyed by `NetworkID`. Only collect the details (and do driver lookups) when STD is
   going to fire for that container, so DNS-only hosts make no extra Docker calls.
4. **`/healthz` stays backward compatible.** `std_status()` feeds `health.py` (~L216),
   the README example JSON and existing tests via `image_info_supported`. Keep that key
   with its current meaning and add `features_supported: {"image_info": bool|null,
   "network_details": bool|null}` (null until the first /meta check). Update the README
   `/healthz` example and field notes.
5. **Bool/int coercion is in `_to_canonical`** (STD module), not in `main.py` ~L241.
   The bad-int warning already exists there ("Could not coerce ... to int; dropping");
   keep it. Make the bool change there: true/1/yes/on → True, false/0/no/off → False,
   anything else → warning naming the container and label, key omitted.
6. **Reserved keys are derived, not hand-listed.** Reserved = `base_kwargs.keys()` ∪
   `{"host", "image_info", "exposure_observations", "timestamp", "skip"}`. A
   `dockernotifier.std.<reserved>` label is dropped with a warning (for `host`, point at
   `HOST_NAME_OVERRIDE`; `skip` is consumed as the opt-out, not warned). Note that a
   `dockernotifier.std.timestamp` label currently passes straight through to STD.
7. **`skip`:** check it before deciding `std_should_fire`, and pop it explicitly from
   the extras rather than relying on the `_to_canonical` whitelist. README: `skip` stops
   reporting; it does **not** remove an entry STD already has (delete it in STD).
8. **Bool typo on a brand-new container:** STD creates a missing health toggle as
   disabled on a new row, so omitting the key still ends up "off" there; on an existing
   row it means "no change". Document this in the README and `docs/decisions.md` as
   accepted.

## Working tree check

Before making any edits, run `git status --porcelain` and cross-reference the files
this plan needs to modify. If any of those files have uncommitted changes, list them
and ask the user before touching them. Surface unrelated dirty files once as
awareness; don't block. This file (the handoff prompt itself) is exempt — it's
expected to be modified by "When done" below.

## What to do

1. **Generalize the STD feature gate** in `notifiers/service_tracker_dashboard.py`.
   - **Replace the single `image_info_supported` flag** with a per-feature check.
     - Add `feature_supported(name)`, for `"image_info"` and `"network_details"`, on the
       same /meta cache, the same rate-limited retry and the same revision-header
       re-check.
     - Keep `image_info_supported()` as a thin wrapper, so existing callers and tests keep
       working.
   - **Track rejections per feature.** Replace `rejected_revision` with a dict keyed by
     feature.
     - `_is_image_info_rejection` becomes `_rejected_features(response)`. It returns the
       set of gated features a 400 blames: `image_info` from `unknown_keys` or from
       `loc[0] == "image_info"`; `network_details` when a detail's `loc` starts with
       `"networks"` and points at one of the four new keys, or reports them as extra
       keys.
     - `_post_register` strips **only the blamed parts** and retries once:
       - drop `image_info`;
       - and/or reduce each `networks` item to `{"name", "aliases"}`.
       - Then mark that feature as rejected at the current revision.
   - **Logging:**
     - Log once per feature when it's unsupported, e.g. "STD at X does not accept
       network_details (API revision N); upgrade STD to 0.13.0+ for network
       details".
     - `std_status()` (used by `/healthz`) reports the per-feature support.
   - **Opt-out:** add the env var `STD_SEND_NETWORK_DETAILS` (default `true`), mirroring
     `STD_SEND_IMAGE_INFO`.
2. **Collect network details** in `main.py` `_extract_networks` (or a new small module if
   that's cleaner).
   - **From the container's own data:** for each `NetworkSettings.Networks[name]`, read
     `IPAddress`, `GlobalIPv6Address`, `MacAddress` and `NetworkID`.
   - **Driver:** it isn't in the container data, so look it up with
     `client.networks.get(NetworkID).attrs["Driver"]`.
     - **Cache it per `NetworkID`.** IDs never change their driver, and the periodic
       refresh re-reads every container every 60 s, so the cache saves one API call per
       network per refresh. Use a bounded dict and look the ID up again on a miss.
     - **Lookup failure** (permissions, network removed): leave `driver` out and log at
       debug level.
     - **`host` network:** the network named `host` is the host network whatever its
       driver. STD treats the name `host` as reserved even without a driver, but send
       `driver: "host"` anyway when Docker reports it.
   - **Validate locally:**
     - parse IPs with `ipaddress` and leave out anything that doesn't parse, or is the
       wrong family;
     - leave out MACs that don't match `xx:xx:xx:xx:xx:xx`;
     - leave out a driver longer than 32 characters;
     - leave out empty strings.
     - A bad value must never cost the container its whole register.
   - **Older STD:** when `feature_supported("network_details")` is false, or the opt-out
     is set, send exactly today's `{"name", "aliases"}` items.
3. **Harden `dockernotifier.std.*` labels** (`main.py` ~L241). These are three real bugs.
   - **Reserved-key collision:**
     - A label whose stripped key collides with a base kwarg (`container_name`,
       `container_id`, `docker_host`, `docker_status`, `image_name`, `stack_name`,
       `started_at`, `action`, `networks`, `exposed_ports`, `published_ports`) makes
       `register(**base_kwargs, **std_extras)` raise `TypeError` ("multiple values"), so
       that container never registers.
     - Drop every such label with a **warning** that names the container and the label.
       Keep the existing `image_info` pop.
   - **`dockernotifier.std.host`:** today it silently overrides the host name in
     `_to_canonical`. Treat it as reserved: drop it with a warning pointing at
     `HOST_NAME_OVERRIDE`, which is the supported way to set the host.
   - **Bool and int labels:**
     - The health toggles (`internal.health`, `external.health` and their `_` variants):
       today anything other than true/1/yes reads as **False**, so a typo like `ture`
       silently turns a check off.
       - Accept true/1/yes/on and false/0/no/off, case-insensitive.
       - For **anything else, log a warning and leave the key out of the payload**, so
         STD keeps what it has. Don't send False.
     - `sort.priority`: an int that doesn't parse is dropped today; keep dropping it, but
       log a warning.
4. **New label `dockernotifier.std.skip=true`.** It means: never report this container to
   STD, even when `STD_REPORT_ALL_CONTAINERS` is on, or the container is listed in
   `dockernotifier.notifiers`.
   - It doesn't affect DNS.
   - Same truthy parsing as above.
   - Log at debug level when a container is skipped.
   - **Don't let it leak into the payload:** STD would reject an unknown `skip` key.
     Check that `_to_canonical`'s whitelist drops it anyway.
   - Notifier-only: no STD change is needed.
5. **Tests** (pytest, `tests/`):
   - **The gate:**
     - per-feature support from /meta;
     - `network_details` unsupported, giving name/aliases-only items;
     - a 400 blaming `networks.0.driver` (or extra keys), giving one retry with stripped
       items while `image_info` stays;
     - a 400 blaming both features;
     - a revision-header change re-checking /meta;
     - `image_info_supported()` still working;
     - the opt-out env var.
   - **Network collection:**
     - IPv4/IPv6/MAC from fake attrs;
     - empty strings left out;
     - an invalid IP or MAC left out;
     - the driver cache: one lookup for two containers on the same network;
     - a driver lookup failure;
     - the `host` network;
     - a macvlan network.
   - **Labels:**
     - a colliding label doesn't crash and logs a warning;
     - the `std.host` label is dropped;
     - a bool typo leaves the key out and logs a warning;
     - a valid false;
     - a bad int;
     - `skip=true` with `STD_REPORT_ALL_CONTAINERS` on, so nothing is sent;
     - `skip` not in the payload.
6. **Docs, all in the same commit, per this repo's Definition of Done:**
   - **`CHANGELOG.md` `[Unreleased]`:**
     - **Added:** network details (STD 0.13.0+, gated, with the opt-out); the `skip`
       label.
     - **Fixed:** the three label bugs, in operator words.
   - **README:**
     - the label reference: `skip`, the reserved keys, the accepted bool values;
     - the env-var table: `STD_SEND_NETWORK_DETAILS`;
     - the STD compatibility table: 0.13.0+ for network details.
   - **`docs/PRD.md`:** the payload section and the revision history.
   - **`CLAUDE.md` Cross-Repo version pairing:** notifier 0.6.0 sends
     `networks[].driver/ip_address/ipv6_address/mac_address`, which needs STD 0.13.0+
     (feature `network_details`).
   - **`docs/decisions.md`:**
     - the reserved-key rule;
     - why `std.host` is not an override;
     - "an unparsable bool leaves the key out, it doesn't send False";
     - the per-network-id driver cache.
7. **Verify:** run this repo's lint and test commands (see `CLAUDE.md` / `ci.yml`). Both
   must be green.

## Conventions to honor

- The notifier's STD and DNS notifiers stay independent: DNS-only installs must be
  unaffected.
- Never send STD a key it hasn't advertised. That is the whole point of the gate.
- Commit prefix `feat:`. No `Co-authored-by:` trailers.
- Write host checks as `urlsplit(url).hostname == ...` (CodeQL).

## When done

1. Update this file's frontmatter: `status` (completed/failed), `completed` (the date),
   `result` (one line).
2. Move this file into `prompts/done/` (success) or `prompts/failed/` (failure). If it's
   still untracked, use a plain `mv`.
3. Record any non-obvious decisions in `docs/decisions.md`.
4. Hand off ONE commit covering this prompt file, the files this session modified, and
   the prompt move. Present the file list and a one-line message (e.g. `feat: send network
   details to STD 0.13.0+ behind a per-feature gate; harden std labels; add std.skip`).
   - **If you are a spawned agent:** do **not** commit. Report the file list + message
     back to the orchestrating session.
   - **If you are running directly:** ask `commit these as "<message>"? (y/n)`. On `y`,
     stage those specific paths and commit on `dev`.
   - Never `git add -A`, never push, never auto-commit.
5. The release itself is a separate step: `/release-prep 0.6.0` in this repo, after the
   operator has validated it.
