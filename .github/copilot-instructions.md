# PACE — Agent Instructions

## Version Bump Checklist

Whenever you make a user-facing change (new sensor, config option, backend behavior, card
behavior, bug fix), bump `"version"` in
[custom_components/pace/manifest.json](../custom_components/pace/manifest.json) (semver: patch
for fixes, minor for new features).

If the change touches any of the 3 Lovelace cards or their shared utils
(`custom_components/pace/www/*.js`), you must **also** update these 3 spots in **every** card
file that imports the shared utils, not just the file you edited:

1. The `Version: X.Y.Z` line in the file's top doc comment
2. The `?v=X.Y.Z` query string on `import { ... } from './pace-card-utils.js?v=X.Y.Z'`
3. The `console.info("%c ... %c vX.Y.Z ", ...)` banner at the bottom of the file

Files that need all 3 updated together: `pace-minimal.js`, `pace-compact.js`,
`pace-dashboard.js`.

**Why this matters**: the Lovelace resource URL (`/local/pace/<card>.js?v=<manifest version>`,
auto-managed by `www_manager.py`) is a *different* cache-bust from the internal
`pace-card-utils.js?v=X` import inside each card. If `pace-card-utils.js` changes but that
internal `?v=` isn't bumped, browsers that already loaded a card keep serving the stale cached
utils file forever — the fix silently never reaches users even after they update and reload Home
Assistant. Always bump both together, even if you only touched `pace-card-utils.js` and not the
card file itself.

## Conventions

- Entity names are hardcoded English strings (`name="..."` on each `EntityDescription`), not
  `translation_key`-derived — this keeps `entity_id` stable across every HA language. See
  `PaceBaseEntity.__init__` in `entity.py`. `translation_key` is still set purely for
  `icons.json` icon lookups.
- Three interchangeable CLI backends live under `custom_components/pace/backends/`
  (`librespeed_cli.LibreSpeedCLIBackend`, `ookla_cli.OoklaCLIBackend`,
  `speedtest_go_cli.SpeedtestGoCLIBackend`), all implementing the `SpeedTestBackend` Protocol in
  `backends/base.py`. Every sensor/binary_sensor/button stays identical regardless of which
  backend is active — only swap/extend code inside `backends/` or the shared coordinator, never
  fork entity definitions per backend.
- Only rename "librespeed"/"LibreSpeed" references that describe **our own** integration (domain,
  class prefixes, entity_id prefixes). Do NOT rename literal upstream references to the real
  LibreSpeed CLI project/binary/GitHub repo inside `backends/librespeed_cli.py` — that backend
  still wraps the actual `librespeed-cli` binary and must keep calling it that.
- The integration supports multiple config entries/instances, so a card's configured `entity_id`
  (e.g. `sensor.pace_download_speed`) will rarely match the real one
  (`sensor.pace_<instance_slug>_<suffix>`). Cards resolve this at runtime via
  `resolvePaceEntity()` in `pace-card-utils.js`, which falls back to a domain+suffix search
  across `hass.states`. Keep each card's `ENTITY_SUFFIXES` map in sync with any new entity.
- Run the Python test suite with
  `source .venv/bin/activate && python -m pytest tests/ -q` from the repo root.
- Whenever you add or change a `config_flow.py` field (a new/renamed `CONF_*` option, its title,
  or its description), update **both** `strings.json` and
  `custom_components/pace/translations/en.json`, **and** add the same key(s) to every other
  locale file under `custom_components/pace/translations/` (`de`, `es-MX`, `fr-CA`, `it`, `nl`,
  `pl`, `pt-BR`, `ru`) — translated, not just copied in English. Missing a locale file means
  non-English users silently fall back to English for that one field while everything else
  around it is in their language, which reads as a bug. This does **not** apply to the Lovelace
  cards' visual editors (`pace-*.js`) — their labels are plain hardcoded English JS strings with
  no i18n system in this codebase, consistent with every existing editor field.
