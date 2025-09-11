# Changelog

All notable changes to this project will be documented in this file.

The format follows a simplified Keep a Changelog style.

## [Unreleased]
- Trainer-wide modifier management (list/add/remove) in GUI/CLI.
- Richer autocomplete with id labels across all pickers.
- Name-based held item catalog (pending item enum) across GUI/CLI.

## [2025-09-11-TE]
- Team Editor: Form & Visuals tab
  - Added new tab with Tera Type (catalog-backed), Shiny + Luck (0 if not shiny, 1–3 if shiny), Pause Evolutions, Gender, and Poké Ball pickers. Changes write to the slot and are saved/uploaded via existing flows.
- Team Editor: EXP ↔ Level synchronization
  - Level is now editable; changing Level updates EXP to the exact growth breakpoint. Changing EXP updates Level using the floor rule. Stats preview updates live.
  - Added read-only Growth Rate label (e.g., “Medium Slow”), normalized from the CSV and matched to exp.ts growth tables.
  - Implemented growth group mapping via `TmpServerFiles/GameData/2/ListOfPokémonByExperienceType.csv`; normalized names (spaces/case) to GrowthRate enum tokens.
- Team Editor: Ability & Passives
  - Simplified UI: removed ability id text/picker from the visible interface (kept logic for future use), kept Passive Enabled, and added an Ability Slot radio (1 / 2 / Hidden). Warning shown when selecting slot 2 (some species lack a second ability).
- Team Editor: Status UX
  - Primary status shows a single contextual field: Sleep turns remaining or Toxic turns. Volatile effects are hidden (battle-only, not persisted).
- Trainer tab (slot scope only)
  - Money and Weather are editable; Play Time and Game Mode are display-only. Added button to open Modifiers/Items manager pre-targeted to Trainer.
- Catalogs & parsers
  - Parsed exp.ts, built JSON tables and helpers `exp_for_level()` / `level_from_exp()`.
  - Parsed pokemon-type.ts to build types catalog and extracted a type matchup matrix from type.ts for future analysis.
  - Parsed pokeball.ts to enable a Poké Ball picker.
  - Added growth map cache under `Source/data/growth_map.json`.

## [2025-09-11]
- GUI: Startup crash fix
  - Fixed AttributeError on launch caused by a missing `_upload_all` handler wired in Data IO. Implemented `_upload_all` to upload `trainer.json` and any present `slot N.json` files (1–5) with confirmations and clear summaries.
  - Kept actions behind the existing `_safe(...)` wrapper to run in the background thread and surface errors in dialogs and the console log.
- UX: Disclaimer enhancements
  - Expanded the top warning to highlight that over-editing can trivialize the game experience, and clarified intended uses: backup/restore, recovery from desync/corruption, and safe personal experimentation.
- Diagnostics
  - Verified Tk/Tcl via pre-load and startup healthchecks; stderr is mirrored to log for native Tk errors.
  - `debug/logs/app.log` and `debug/logs/app_state.json` record run outcomes and environment to speed up future triage.

## [2025-09-10-2]
- Session lifecycle
  - Always establish a fresh clientSessionId on successful login (prefer server-provided; else generate).
  - GUI: Added "Refresh Session" button next to Login to re-login and rotate the session id.
  - GUI: Added "Last session update" label persisted per user.
  - CLI: Added menu option to refresh session (re-login and rotate clientSessionId).
- Base stats and stat inference
  - Added `Source/data/base_stats.json` importer (debug/tools) and runtime loader.
  - Team Editor now prefers catalog base stats; when missing, reverse-infers base stats by removing item and nature multipliers before computing.
  - Calculated stats apply nature then item multipliers; inference divides them out.
- Selectors write numeric IDs, with labels for clarity
  - Move pickers set move ID in the field; adjacent label shows name + id.
  - Starter picker sets dex ID; added adjacent label showing display name + id.
- Modifiers & Items Manager
  - Consolidated on a single manager; removed legacy Modifiers Manager from code paths.
  - Added optional post-upload verification (compare modifiers with server).
- Team Editor verification
  - After upload, optional verify compares party with server and shows diff when mismatched.
- Data IO
  - Added "Dump All" (trainer + slots 1-5) with overwrite confirmation.
  - Dump Trainer/Slot prompt before overwriting existing local dumps.
  - Slots Refresh now reads local dumps only (no server fetch) and shows last local timestamp.

## [2025-09-10]
- GUI: Starters UX
  - Added a "Pick..." button next to the Pokémon selector to choose starters from a searchable catalog.
  - Kept Pokémon autocomplete; selection now sets the text box directly for clarity.
  - Separated sections: "Starter Unlock & Data" vs "Eggs & Tickets"; moved Pokedex action next to unlock controls and clarified candies apply to the selected starter.
- GUI: Output dialogs for analysis/tools
  - Analyze Team, Analyze Run Conditions, List Modifiers, and Pokedex now show results in a scrollable dialog (and still log to console) instead of only printing to the console.
  - Added a Save… button in dialogs so users can choose to save reports after reviewing them.
  - Added "Analyze Modifiers" action to summarize modifier types, player vs targeted counts, and most-targeted party ids.
- GUI: Feedback/async
  - All new actions run asynchronously and provide message dialogs for success/failure where applicable.
- Dev: Minor layout tidy-up in Starters and Modifiers sections.
- GUI: Items UX
  - New Item Manager dialog with party picker, current per-mon modifiers view, and curated/observed item pickers (Common, Accuracy with boost, Berries, Base Stat Booster, Observed from dumps).
  - Keeps quick Add/Remove Item actions for power users.
  - Team Editor shows an "Item effects (preview)" line highlighting common stat-impacting items (scaffolding for stat calc integration).
  - Simplified Modifiers/Items section: primary actions are Item Manager, Modifiers Manager, and Analyze Modifiers. Removed redundant top-level Add/Remove and List Modifiers in favor of dedicated managers and analysis dialog.
  - Stat multipliers: Calculated Stats in Team Editor now apply 10% per stack for stat-boosting modifiers (e.g., BASE_STAT_BOOSTER per selected stat; common items like CHOICE_BAND/SPECS/SCARF, EVIOLITE, MUSCLE_BAND, WISE_GLASSES). Added UI to adjust stacks in Team Editor and Item Manager.
  - Unified target management: Item Manager now supports Trainer or Pokémon targets, shows applicable modifiers per target, and lets you add/edit/remove with confirmations. Stacks are clamped to non-negative.
  - Selection retention: Adding/editing modifiers in Item Manager does not change the current Pokémon selection.
 
- GUI: Layout
  - Moved the Console to a right-side pane (narrower, taller) to give more room to the main controls. Left side stacks Login, Actions, and feature sections in a taller column.

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
