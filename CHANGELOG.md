# Changelog

All notable changes to this project will be documented in this file.
Format based on Path of Building changelog style, adapted for MCP tooling.

> **Community Project**: This is an independent, fan-made project built out of love for Path of Exile 2. Not affiliated with or endorsed by Grinding Gear Games.

---

## Unreleased

--- MCP Tools ---
* `calculate_character_dps` now covers weapon-attack skills (bow/melee), not just spells. Passing `weapon_damage` routes the call to a new `AttackDPSCalculator` (`src/calculator/attack_dps_calculator.py`) instead of `SpellDPSCalculator` — fixes Tornado Shot / Ice Shot / Snipe (and any other skill with a `baseMultiplier` in `skill_gems_v2.json`) coming back "not resolvable", since those skills scale off weapon damage rather than an innate spell base and the calculator only understood the latter. The spell path's failure message now also detects when a queried name is actually an attack skill and points the caller at `weapon_damage` instead of a dead end
* Add `resolve_attack_from_v2` (`src/calculator/v2_spell_db.py`), the attack-skill counterpart to `resolve_spell_from_v2` — derives damage effectiveness (`levels[N].baseMultiplier`) and a skill-innate attack-speed modifier (`levels[N].attackSpeedMultiplier`) from the same v2 extraction
* Factor the DoT-layer renderer (#159) out of `_handle_calculate_character_dps` into a shared `_build_dot_section` helper so both the spell and attack paths can attach an optional damage-over-time layer without duplicating the ~90-line block

--- Testing ---
* Add `tests/test_attack_dps_calculator.py` (pure-math coverage: weapon damage averaging, effectiveness scaling — including that it applies to added flat damage the same way spell damage effectiveness does — increased/more stacking, crit weighting, attack-speed combination, resistance application)
* Extend `tests/test_v2_spell_db.py` with `resolve_attack_from_v2` coverage against the real Ice Shot / Tornado Shot / Snipe records, including the Snipe gem-level-1 edge case (no `baseMultiplier` at that tier — channel-charge entry) resolving to `None` rather than crashing

## Version 1.0.4 (2026-06-16) - permissioned self-update

Closes the "no data release published" gap and adds a consent-based self-update path so the server updates its game data and code only with the user's permission.

--- MCP Tools ---
* Add `check_for_updates` (#191). Reports game-data and code freshness across both layers and, with `apply=true` (explicit consent), applies pending updates. Packaged/.mcpb installs get reinstall guidance; git installs fast-forward `main`

--- Infrastructure ---
* Add a three-mode consent model to data distribution (#191). `ensure_data_current` now gates *upgrades* behind consent (`POE2_MCP_AUTO_UPDATE=1` or `apply=true`); a fresh-install *bootstrap* (no local data) still proceeds automatically since the server can't run without data
* Add `src/data/update_manager.py` (#191). Unifies data + code update detection, install-kind detection (git vs packaged), and consent-gated application
* Fix Windows fd-leak crash in `publish_data_release.py` (#191). `mkstemp`'s file handle was left open, so the post-upload `unlink` failed with WinError 32 *after* the release succeeded
* Un-ignore `src/data/update_manager.py` from the root-scratch `update_*.py` gitignore glob (#191)

--- Data ---
* Publish the `data-v0.5.0-1` game-data release (#191). First `poe2-data.zip` bundle (12 canonical files); activates `data_distributor` and the `.mcpb` CI auto-build

## Version 1.0.3 (2026-05-31) - skill_gems shipped + zero-coverage gap sweep

Follow-up to 1.0.2 the same day. Closes the last 0.5-pending dataset (`skill_gems`), adds the operator/AI-facing docs that were missing across the repo, and lands ~200 new tests filling zero-coverage gaps on load-bearing pure-function modules.

--- Game Data ---
* Ship `data/game/skill_gems/skill_gems.json` (#91). 872 gems extracted from PathOfBuilding-PoE2 `origin/dev @ 9c2bf0316` (patch-day 2026-05-30 commit). 100% gem→effect join rate via `grantedEffectId`. Schema v1: gem metadata (tier, tags, requirements, naturalMaxLevel) + granted_effect (levels with cost/crit_chance/level_requirement, stat_sets with base_effectiveness). 1.6 MB output. `version.json` bumped to `data-v0.5.0-r7`; `datasets_pending_0_5_reextract` is now empty. v1 deliberately defers full Lua `statMap` / `baseFlags` / `constantStats` / `stats` extraction (needs structural Lua parser; tracked for v2)
* Refresh `data/game/README.md` for the 0.5-r5 dataset state (#82). Removed stale "pending re-extract" markers on ascendancies/support_gems/stats; per-dataset table replaces the prose status block

--- Documentation ---
* Add `docs/AI_ASSISTANT_GUIDE.md` (#81). Onboarding doc for AI clients (Claude/ChatGPT/Cursor/Windsurf etc.) — tool surface, parameter alias quirks, game-data sources, known failure modes (incl. CRITICAL #4), common LLM mistakes, workflow patterns
* Add `docs/EXTRACTION_PIPELINE.md` (#84). End-to-end data/game/ regeneration walkthrough — LibBundle3 + pythonnet setup, the 0.5-era gotchas (CoreCLR runtime, parsePaths=False workaround, balance/ subdir, mods row size growth 661→677, ascendancy offset 44), lifecycle checklist for new patches
* Add `docs/SKILL_GEMS_PORT_AUDIT.md` (#85). Scout for the (then-)pending extractor port — PoB2 source shape, existing extractor gaps, recommended schema, open questions. Set up the work that #91 then delivered
* Add `web/README.md` (#86). First README for the standalone Svelte 5 + Vite Timeless Jewel Seed Calculator subproject — tech stack, dev/build/deploy commands, GitHub Pages auto-deploy workflow walkthrough

--- Testing ---
* Add `tests/test_game_data.py` (#83). 19 tests covering the `src/data/game_data.py` base API (path constants, get_version, load_*() helpers, load_metadata, describe). Notable: `test_load_stats_record_count_matches_version_manifest` catches drift between `stats.json` and `version.json` on re-extract
* Add `tests/test_mods_spec.py` (#87). 48 tests for `src/parsers/specifications/mods_spec.py` (central binary parser used by every mod tool). Locks in PR #68's 0.5 row-size relaxation as an explicit regression guard
* Add `tests/test_characters_spec.py` (#88). 27 tests for `src/parsers/specifications/characters_spec.py` (poe.ninja class → PSG starting-node resolution). Cross-consistency tests catch silent drift between `POE_NINJA_CLASS_TO_STARTING_NODE` and `PSG_STARTING_NODES`. Locks in the "poe.ninja calls Druid 'Sorceress'" quirk
* Add `tests/test_defense_calculator.py` (#89). 37 tests for `src/calculator/defense_calculator.py`. Regression guards on the PoE2-vs-PoE1 constants (block cap 50% not 75%, ES recharge 12.5%/s not 20%, ES delay 4s not 2s)
* Add `tests/test_game_data_helpers.py` (#90). 26 tests for the convenience helpers added by PR #80 (find_ascendancies_by_base_class, find_mods_by_stat_id, get_keystones, etc.). Direct continuation of scope deferred from #83
* Add `tests/test_spell_dps_calculator.py` (#92). 41 tests for `src/calculator/spell_dps_calculator.py` (last unmonitored calculator). Anchored to docstring examples; locks in `more` multipliers stacking multiplicatively (not additively — common subtle-correctness trap)

--- Known Issues (carried over from 1.0.2) ---
* CRITICAL #4: poe.ninja builds-list / ladder SPA migration broke `compare_to_top_players` and HTML-scrape fallback (#61). Underlying fix needs the new poe.ninja endpoint reverse-engineered

---

## Version 1.0.2 (2026-05-31) - Patch 0.5 game data + MCP usability sweep

Follow-up to 1.0.1. Where 1.0.1 was non-extraction code compat for the 0.5 patch, 1.0.2 ships the actual extracted 0.5 game data + MCP-handler improvements + accuracy work surfaced during a fresh end-to-end MCP evaluation.

--- Game Data (canonical layout) ---
* Establish `data/game/{dataset}/` repo-as-source-of-truth layout (#69). 5 datasets shipped: mods (16,788 records), passive_tree (9,605 nodes, 82 keystones, 2,151 notables), support_gems (680), ascendancies (37 — including NEW 0.5 Spirit Walker + Martial Artist), stats (26,943 stat IDs). Closes #53 (pip install empty database).
* Inline-resolve `stat_id` strings on every non-empty mod stat entry (#75). 24,632 entries enriched. Consumers no longer need to load `stats.json` separately to resolve `stat_key` references.
* Fix ascendancy `display_name` field — use canonical offset 44 instead of longest-string heuristic (#71). 23 active ascendancies all correctly named.

--- MCP Tools ---
* Add `check_tree_freshness` self-diagnostic tool (#76). Compares local `data/game/version.json` patch_version against poe.ninja's current `PassiveTree` tag from index-state. Reports current / behind / ahead / unable. Pure change-detection per data policy. Tool count: 39 → 40.
* Rewrite `search_mods_by_stat` (#73). Was returning 0 results for "life regeneration" despite 16,788 mods in DB. Now tokenizes the query and searches mod_id + display_name + resolved stat_id strings. Verified: "life regeneration" goes from 0 hits to 173 hits (117 mod_id + 56 stat cross-reference).
* Accept alias parameter names on `inspect_keystone` (`name`), `inspect_spell_gem` (`name`, `gem_name`), `validate_support_combination` (`support_gem_names`, `names`) via `oneOf` in inputSchema (#73). AI-friendliness fix from the May eval.
* SPA-aware character-fetch error templates on `analyze_character` and `compare_to_top_players` (#74). Surfaces the CRITICAL #4 (#61) poe.ninja SPA migration cause up front instead of sending users on a wild-goose chase through profile-privacy and account-format settings. Closes #55 (@dsakura).

--- API ---
* Auto-discover league slug from index-state when `LEAGUE_MAPPINGS` is stale (#62, in 1.0.1 retro). Future leagues work as soon as poe.ninja indexes them, without needing a static map update.

--- Knowledge ---
* Add `Runic Ward` `explain_mechanic` entry (#64, in 1.0.1 retro). PRELIMINARY — numeric mechanics not bundled (waiting on .datc64 mechanics extraction). Documents what we know, what's pending.

--- Documentation ---
* Split Claude Desktop config in README into pip-install (`"command": "poe2-mcp"`) vs source-install (`launch.py`) sub-options (#72). Closes #52.

--- Known Issues (carried over from 1.0.1) ---
* CRITICAL #4: poe.ninja builds-list / ladder SPA migration broke `compare_to_top_players` and HTML-scrape fallback (#61). Per-character JSON API still works for characters in the snapshot; #74 + #65 surface the cause to users instead of silent fail. Underlying fix needs the new poe.ninja endpoint reverse-engineered.
* `skill_gems` dataset not yet in `data/game/` — blocked on PoB2 community shipping 0.5 `tree.json` upstream (verified daily; still not landed as of 2026-05-31). Current pre-0.5 skill data in `data/pob_active_skills.json`.

---

## Version 1.0.1 (2026-05-30) - Patch 0.5 "Return of the Ancients" Compatibility

Compatibility updates for PoE2 Patch 0.5 (released 2026-05-29). Code-level fixes that work without re-extracted game data. Local passive tree and item mod data remain stale pending `.datc64` re-extraction; see Known Issues below.

--- API ---
* Add Runes of Aldur league (+ HC/SSF/HCSSF variants) to `LEAGUE_MAPPINGS` (#59). Slugs confirmed via `/poe2/api/data/index-state`: `runesofaldur`, `runesofaldurhc`, `runesofaldurssf`, `runesofaldurhcssf`
* Update default league from stale "Abyss" to "Runes of Aldur" on `get_character` and `_scrape_character_page` (#59)
* Auto-discover league slug from index-state when `LEAGUE_MAPPINGS` is stale, so future leagues work before the static map is updated (#62)

--- Calculators ---
* Stub `runic_ward` field on `DefensiveStats` for PoE2 0.5 Verisium Runeforging defense layer (#59). Not yet layered into mitigation; requires local extraction

--- Knowledge ---
* Add `Martial Artist` (Monk) and `Spirit Walker` (Huntress) to `ASCENDANCY_TO_CLASS` (#59). Class mapping only; node data pending re-extraction
* Commit `src/parsers/ascendancy_resolver.py` as a tracked module (#59). Was previously imported by `mcp_server.py` but untracked, so fresh checkouts would fail to import

--- Bug Fixes ---
* Fix pip console entry-point `poe2-mcp` invoking async `main()` without `asyncio.run()` (#60). Closes #56 (@MagicJoseph)

--- Documentation ---
* Correct README tool count from 32 to 39 and document the live Path of Building bridge (`pob_*` tools) (#58)

--- Infrastructure ---
* Bump vite 7.3.1 to 7.3.3 in /web (#50, dependabot)
* Bump postcss 8.5.6 to 8.5.14 in /web (#51, dependabot)

--- Known Issues (extraction-dependent, not in this release) ---
* CRITICAL: poe.ninja builds-list / ladder SPA migration broke `compare_to_top_players` and the HTML-scrape fallback (#61). Per-character JSON API still works but returns 404 for characters not present in the snapshot version (excludes freshly-rolled characters)
* Local passive tree pre-0.5: 16.21% miss rate measured vs poe.ninja's `PassiveTree-0.5` asset (4,480 nodes; local 4,094). Pending `.datc64` re-extraction
* Ascendancy node data stale for 6 reworked ascendancies + 2 new ones; mapping in place, node data pending re-extraction
* Item mod DB missing Runic Ward / Runeforging mods; pending re-extraction
* `runic_ward` field exists on `DefensiveStats` but is not layered into `calculate_ehp`; pending mechanics extraction

---

## Version 1.0.0 (2025-12-16) - First Major Release

The first stable release of the PoE2 Build Optimizer MCP server. Provides 32 MCP tools for AI-powered character analysis and build optimization.

--- Core Features ---
* 32 registered MCP tools for character analysis, validation, and optimization
* Multi-source character fetching (poe.ninja, official API, HTML scrape fallback)
* Path of Building import/export support
* Comprehensive game mechanics knowledge base

--- MCP Tools ---
* Character analysis: `analyze_character`, `compare_to_top_players`, `import_poe_ninja_url`
* Validation tools: `validate_support_combination`, `validate_build_constraints`
* Gem inspection: `inspect_support_gem`, `inspect_spell_gem`, `list_all_supports`, `list_all_spells`
* Passive tree: `list_all_keystones`, `inspect_keystone`, `list_all_notables`, `inspect_passive_node`
* Base items: `list_all_base_items`, `inspect_base_item`
* Item mods: `inspect_mod`, `list_all_mods`, `search_mods_by_stat`, `get_mod_tiers`, `validate_item_mods`
* Path of Building: `import_pob`, `export_pob`, `get_pob_code`
* Knowledge: `explain_mechanic`, `get_formula`

--- Token Optimization ---
* Pagination support with `limit` (default 20) and `offset` parameters
* Detail level filtering (`summary`, `standard`, `full`) for response verbosity control
* Compact output format with abbreviated JSON keys for programmatic consumption

--- Data Sources ---
* 4,975+ passive tree nodes with full stat text
* 335+ ascendancy nodes (99% coverage)
* 14,269 item modifiers (prefixes, suffixes, implicits)
* Complete skill gem data from Path of Building
* Support gem effects and interaction data

--- Infrastructure ---
* SQLite database with async support (aiosqlite)
* Multi-tier caching (memory -> Redis optional -> SQLite)
* Rate limiting with exponential backoff
* Comprehensive test suite

---

## Prior Development History

See git commits before 2025-12-16 for development history leading to v1.0.0.
