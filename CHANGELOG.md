# Changelog

All notable changes to this project will be documented in this file.

The format follows a simplified Keep a Changelog style.

## [Unreleased]
- Trainer-wide modifier management (list/add/remove) in GUI/CLI.
- Richer autocomplete with id labels across all pickers.
- Name-based held item catalog (pending item enum) across GUI/CLI.

## [2025-09-10]
- GUI: Starters UX
  - Added a "Pick..." button next to the Pokémon selector to choose starters from a searchable catalog.
  - Kept Pokémon autocomplete; selection now sets the text box directly for clarity.
- GUI: Output dialogs for analysis/tools
  - Analyze Team, Analyze Run Conditions, List Modifiers, and Pokedex now show results in a scrollable dialog (and still log to console) instead of only printing to the console.
  - Added "Analyze Modifiers" action to summarize modifier types, player vs targeted counts, and most-targeted party ids.
- GUI: Feedback/async
  - All new actions run asynchronously and provide message dialogs for success/failure where applicable.
- Dev: Minor layout tidy-up in Starters and Modifiers sections.

## [2025-09-09]
- GUI: Backup/Restore
  - Fixed latest backup detection to use `user_save_dir(<user>)/backups`; "Last backup" now shows the newest timestamp.
  - Unified restore dialog: lists timestamped backups and offers scope options (All, Trainer only, Specific Slot). Delete includes "latest/last" warnings.
- GUI: Upload and file consistency
  - Renamed Data IO actions to "Upload Trainer (trainer.json)" and "Upload Slot (slot N.json)" for clarity.
  - Added "Upload Local Changes..." to push trainer and/or selected slot from local dumps.
  - Added "Open Local Dump..." to open `trainer.json` or `slot N.json` with the OS default editor.
  - Team Editor upload writes the in‑memory state to `slot N.json`, then reads that file and uploads exactly that payload. Slot uploads across the app consistently use the same selected slot index.
  - Modifiers/Items and Run Weather editors save to `slot N.json` and re‑read that file for upload to ensure file⇄server parity.
- GUI: Starters
  - Added "Hatch All Eggs After Next Fight" button.
- GUI: Team Editor – Calculated Stats, IVs, Nature
  - Added Calculated Stats block (HP/Atk/Def/SpA/SpD/Spe) that updates live when IVs change.
  - Uses stat formulas with EV term shape retained (EVs currently treated as 0), and reverse‑infers base stats from existing actual stats on load.
  - Implemented nature multipliers (+10%/−10% on non‑HP stats). Stat block shows (+)/(−) markers.
  - Nature dropdown displays effect (e.g., "Adamant (+Atk/−SpA)"); added adjacent hint label "+Atk / −SpA" or "neutral".
- CLI: Restore from backup now prompts for scope (all/trainer/slot) and restores accordingly.
- Bugfix: Removed stray UI reference in `_update_backup_status` that caused a Tkinter NameError.
- Consistency: Refresh, dump, open, and upload all target the same per‑user files under `Source/saves/<user>/`.
- Data: Added `Source/data/nature_effects.json` and catalog helpers `load_nature_effects()` and `nature_multipliers_by_id()`.
- GUI: Introduced non-blocking Tkinter UI with background tasks and progress bar.
- GUI: Added scrollable Actions panel and mouse-wheel support for lists.
- GUI: Mode selector (CLI prompts or `--gui` flag) to run in GUI or CLI.
- GUI: Data IO with slot dropdown (dump/update), backups restore dialog.
- GUI: Slots summary (slot, party size, playtime, local dump time), empty slots greyed.
- GUI: Team Editor dialog
  - Autocomplete for moves, ability, nature; searchable catalog picker dialogs.
  - IV grid with two-column layout (HP/Atk/Def | SpA/SpD/Spe) and clamped 0–31.
  - Held item editing (id or name if items catalog present).
  - Save to file + Upload separation.
  - Add new Pokémon into party.
- GUI: Starters tab
  - Pokémon selector (autocomplete) and abilityAttr/passiveAttr presets.
  - valueReduction input; candies and gacha ticket deltas (save then optional upload).
- GUI: Modifiers
  - Modifiers Manager dialog for player and Pokémon:
    - Lists grouped modifiers with removal by index.
    - Add player modifier (typeId, args, stack) with local save + optional upload.
  - Quick add/remove Pokémon items: WIDE_LENS, MULTI_LENS (boost), FOCUS_BAND, BERRY, and common one-arg items.
  - BASE_STAT_BOOSTER with stat selection from catalog.
- CLI: Reorganized and renumbered menu into sections with safety confirmations.
- CLI: Added Tools → build catalogs from tmpServerFiles and clean dev artifacts (debug/, tmpServerFiles/, env data).
- API: Modular split under `Source/rogueeditor/` (api, editor, config, utils, token, catalog).
- API: Adopted canonical endpoints: system/session GET/UPDATE with `clientSessionId`.
- API: Server slot indexing set as zero-based; UI remains 1–5.
- Auth: Fixed `authorization` header to send raw base64 token.
- Data catalogs: Added clean JSON catalogs under `Source/data/` (moves, abilities, ability_attr, natures, weather, stats, modifiers, berries, items if available).
- Storage: Per-user dumps under `Source/saves/<username>/` (trainer.json, slot N.json) with timestamped backups.
- Legacy: `Source/RogueEditor.py` now delegates to modular CLI for unified UX.
- Misc: Added project `.gitignore` to exclude local data, debug artifacts, tmp files.

## [2025-09-08]
- Initial modular CLI prototype and per-user path groundwork.
- Token header and endpoint fixes; preliminary catalogs and utilities.

[Unreleased]: ongoing
