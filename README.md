# rogueEditor

Pokerogue.net save editor for trainers and run data, with both CLI and GUI.

Repository: https://github.com/OmarAtieh/rogueEditor

Discord: Oviren

## Features

- GUI and CLI modes
  - GUI: Non-blocking, scrollable UI with autocomplete pickers and save vs upload separation.
  - CLI: Structured menu with safety confirmations and per-user paths.
- Team editor enhancements
  - Basics: species + type chips header (form-aware) with server stats in the header row; base stats prefer `Source/data/pokemon_catalog.json`.
  - Per-Pokémon Type Matchups (form-aware): vertically stacked bins (x0, x0.25, x0.5, x1, x2, x4) with wrapped chips.
  - Trainer Team Summary: team members list (with form + type chips), overview with counts per type per bin, and a “Top Risks” section.
  - Right-click context menus on text inputs (cut/copy/paste/select-all).
  - Heal actions: Full Restore (current Pokémon) and Full Team Heal (local only; upload to sync changes).
- Per-user saves and backups
  - Saves stored under `Source/saves/<username>/` (trainer.json, slot N.json).
  - Timestamped backups and a restore dialog (restore all/trainer/slot, delete backups with warnings).
- System/Session aware API
  - Uses `/savedata/system/*` and `/savedata/session/*` with `clientSessionId`.
  - UI shows slots summary; server indexing is 0-based (UI uses 1-5).
- Team editor
  - Level, IVs (two-column layout with clamped 0-31), moves (name/id), ability (name/id), nature (name/id), held item (id or name if catalog available).
  - Add a new Pokemon to the party.
- Starters
  - abilityAttr/passiveAttr presets, cost reduction (valueReduction), candies increment, gacha deltas.
- Modifiers / Items
  - Manager dialog for player and Pokemon modifiers; add/remove and upload.
  - Quick item templates (WIDE_LENS, FOCUS_BAND, BERRY, etc.) and BASE_STAT_BOOSTER with stat selection.
- Data catalogs
  - Clean JSON catalogs in `Source/data/` (moves, abilities, ability_attr, natures, weather, stats, modifiers, berries, items if available).
  - Builder tool to parse tmpServerFiles once; runtime uses only `Source/data`.
  - Type matrix: generated from `TmpServerFiles/GameData/2/PokemonTypeMatchupChart.csv` (defense by columns, attack by rows), cached in `Source/data/type_matrix.json`.

## Requirements

- Python 3.10+
- `requests`

Install dependencies:

```
pip install requests
```

## Run

CLI (default):

```
python Source/cli.py
```

GUI:

```
python Source/cli.py --gui
```

Non-interactive smoke (requires `.env/env_data.txt` or prompt input):

```
python Source/cli.py --noninteractive
```

## Usage Tips

- First run: Build catalogs (CLI Tools → 20) to generate `Source/data` from `tmpServerFiles/GameData` (optional; recommended before deleting tmpServerFiles).
- clientSessionId: Generated or persisted per user automatically; can be provided via `--csid`.
- Backups: Backup/Restore prominently available near login in GUI; latest backup shown. Restore supports ALL, Trainer only, or specific slot.
- Save vs Upload: Most editors save to local JSON first, then prompt to upload to the server.

## Ethics & Intended Use

- Editing saves can easily trivialize progression and reduce enjoyment. Please be mindful.
- This tool exists to help you:
  - back up and restore your own data,
  - recover from corrupt or desynced saves,
  - and safely experiment on your own account.
- Always back up before making changes. Use at your own risk.

## Notes

- This project is a significant rework and differs from the original repo. It follows a modular structure under `Source/rogueeditor/` for long-term maintainability.
- Use responsibly. Always back up your data before making changes.

## Changelog

See `CHANGELOG.md` for recent changes and roadmap.
