# Team Editor Enhancements Plan (Slot-Scoped)

This plan tracks upcoming improvements to the Team Editor focused on slot/session data. It is designed for smooth context handoffs and incremental delivery.

## Goals

- Surface and safely edit common, persistent run properties for Pokémon party and Trainer (slot scope).
- Add catalogs and logic to support EXP↔Level synchronization via growth curves.
- Improve moves management (PP fields), and visuals/form controls (Tera, Shiny, Gender, Poké Ball).
- Prepare a types matchup generator for future analysis features.

## Phase 1 — Catalogs from TmpServerFiles/GameData/2

Parse new TS sources and expose catalog accessors in `rogueeditor.catalog`:

- `exp.ts` — EXP tables by growth group. Notes:
  - 5 growth speeds defined; infer which index corresponds to which group.
  - Provide helpers: `level_from_exp(group, exp)` and `exp_for_level(group, level)` (ceil/floor rules below).
  - Rule: setting Level uses the exact breakpoint EXP for that level; setting EXP updates Level to the floor of the EXP (not above).
- `pokeball.ts` — id/name mapping (for Poké Ball picker).
- `pokemon-types.ts` — mapping species → types (for future; optional now).
- `types.ts` — type matchup; build a matrix (type→type→mult). Not used immediately; keep a generator utility.

Artifacts:
- JSONs under `Source/data/` where practical (mirroring existing catalogs).
- Accessor functions in `rogueeditor.catalog` (e.g., `load_pokeball_catalog()`, `load_tera_types()` if needed, etc.).

## Phase 2 — UI: Pokémon Form & Visuals tab

Add a new tab under Pokémon with:
- Tera Type picker (dictionary-based)
- Shiny toggle
- Luck (0 if non‑shiny, 1–3 if shiny; enforce and sync with shiny)
- Pause Evolutions toggle (`pauseEvolutions`)
- Gender picker
- Poké Ball picker

All fields update the slot snapshot; Save/Upload persists as today.

## Phase 3 — Ability Selection

Replace freeform ability edit with a radio selector for ability index:
- Radio: 1, 2, 3 (Hidden). When selecting 2, show a warning tooltip that some species do not have a second ability.
- Sync with direct ability id when present; prefer ability index pathway when both exist to avoid conflicts.

## Phase 4 — EXP↔Level Synchronization

Implement growth curves using `exp.ts`:
- Pokémon have a growth group; infer via mapping (to be sourced) or fallback default.
- Level becomes read‑only; EXP is editable.
- On EXP change: compute `level_from_exp(group, exp)` (floor rule).
- On Level edit: set EXP to the exact breakpoint `exp_for_level(group, level)`.
- Update displayed Level immediately and mark slot dirty.

Assumption beyond level 100
- Until official post‑100 curves are available, levels above the last table entry are linearly extended using the last delta (EXP[L_max] − EXP[L_max−1]).
- This is subject to change if more accurate data becomes available.

## Phase 5 — Basics Tab Improvements

- Show server `stats` array (read‑only) in Basics (displayed alongside Level, now read‑only)
- Level becomes read‑only; EXP becomes editable (see Phase 4)
- Keep detailed calculated stats in the existing Stats tab (unchanged)
- Status remains as implemented: Sleep/Toxic with contextual field; volatile hidden

## Phase 6 — Moves Tab Enhancements

- Show and edit `ppUp` and `ppUsed` per move (preserving existing `moveset` shape)
- Add helper buttons:
  - “Set PP to current max”: update `ppUsed` = current max – current PP (per move)
  - “Max PP Ups”: set `ppUp` to the maximum allowed for the base PP (per move rules)

Notes:
- For `moveset`, retain dict entries and untouched keys (e.g., `ppUp`, `ppUsed`).
- Ensure id source stays in the same key (`id` vs `moveId`).

## UI Fields to Surface (Summary)

Pokemon Basics (read‑only unless noted):
- Level (read‑only once EXP sync lands), Nature (decorated), Ability (radio 1/2/Hidden), server `stats` array (read‑only), Status with contextual counter

Pokemon — Form & Visuals tab (editable):
- Tera Type, Shiny, Luck (0 if not shiny; 1–3 otherwise), Pause Evolutions, Gender, Poké Ball

Pokemon — Moves tab (editable):
- Moves (existing), plus `ppUp` and `ppUsed`; “Set PP to current max” and “Max PP Ups” helpers

Trainer (slot) tab (editable unless noted):
- Money, Weather; Play Time (display‑only), Game Mode (display‑only); quick open Modifiers/Items manager (Trainer target)

## Constraints & Rules

- Luck: enforce 0 when not shiny; restrict to 1–3 when shiny
- Ability selection: show a warning when picking ability 2 (some species lack a second ability)
- EXP↔Level: Level read‑only once growth curves added; editing EXP recomputes Level via floor; editing Level (if allowed) sets EXP to breakpoint
- Never modify battle‑only state (volatile, summon/battle data)

## Next After UI Fields

- Implement growth curves and EXP↔Level sync (Phase 4)
- Add Poké Ball and Tera catalogs and wire into selectors (Phase 1/2)
- Prepare type matchup artifacts (Phase 8) for future team analysis

## Open Questions / TODOs

- Source for species → growth group mapping (to power EXP↔Level)
- Confirm Tera types catalog source and structure
- Ability id vs index precedence: prefer index in UI, map to id consistently

## Phase 7 — Types Matchup Generator (Future)

- Convert `types.ts` into a matchup table stored under `Source/data/types_matrix.json`.
- Provide helpers to compute effectiveness, team weaknesses/strengths (for future UI features).

## Implementation Notes

- Follow existing parser patterns in `rogueeditor.catalog` (e.g., `_parse_ts_enum`) and add specialized parsers as needed for arrays or nested objects in the new TS files.
- Preserve original shapes when writing: `moveset` dict entries, status objects, etc.
- Never write battle‑only state (volatile, summonData, battleData).
- Slot‑scoped Trainer tab only manipulates fields in slot (money, weather, playTime read‑only, gameMode read‑only). Trainer.json editing remains on main screens.

## Status & Next Steps

- Current: Team Editor basics, stats coloring, Trainer tab (money, weather, playtime+mode display), status UI.
- Next: Phase 1 (parse new catalogs), then Phase 2 (Form & Visuals tab), then Phase 6 (PP fields & helpers) — these offer the highest user value quickly.

## 2025-09 Updates (Implemented)

- Basics
  - Added species + types chips header (form-aware) and moved server stats to header.
  - Pushed other controls down to avoid overlap; tightened Ability radio layout.
  - Party list shows DEX4 + species + form + id + level.
  - Stats tab now prefers `pokemon_catalog.json` base stats.
- Per-Pokémon Type Matchups (new tab)
  - Vertically stacked bins: Immune (x0), x0.25, x0.5, x1, x2, x4; chips wrap to new lines.
  - Form-aware typings from catalog forms when present; cached per-mon vectors.
- Trainer Team Summary (new tab)
  - Left: members (with form + type chips). Right: team bins overview. Bottom: Top Risks highlighting ≥3 weak overlaps.
  - Heal actions: Full Team Heal (local-only; user uploads to sync to server).

- Heal buttons (Basics)
  - Full Restore: clears status, sets HP to server max HP from slot file, restores PP (local-only; user uploads to sync).
