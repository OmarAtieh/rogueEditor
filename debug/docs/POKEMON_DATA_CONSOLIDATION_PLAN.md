Good progress. Here’s a tightened, developer-ready plan that aligns with what you built, fixes the thumbnail roadblock, and adds types + growth rates. I verified the four files you shared and list exact columns and quirks, then give a one-pager you can paste into your task.

## What’s actually in the four files (verified)

* List of Pokémon by base stats.xlsx (Sheet1)
  * Columns (header row 0): `#`, `Pokémon`, `Unnamed: 2`, `HP`, `Attack`, `Defense`, `Sp. Attack`, `Sp. Defense`, `Speed`, `Total`, `Average`.
  * `Unnamed: 2` is the species name.
  * Form behavior: the file uses trailing form-label rows with `#=NaN` and all stats empty (e.g., Mega Charizard X, Alolan Form) that belong to the stat row above.
  * Range: `#` is continuous from 1 to 1025 with no dex gaps in this sheet.
  * Images: pandas won’t show images; the workbook itself has only one embedded image (a generic sheet object, anchored around row ~809). It does not contain per-row thumbnails. Your renamer failed because there is no reliable image-row mapping to extract here.

* ListOfPokemonByType.xlsx (Sheet1)
  * Columns (header row 0): `Generation I`, `Unnamed: 1`, `Unnamed: 2`, `Unnamed: 3`, `Unnamed: 4`. Data begins at row 1.
  * `Generation I` holds Ndex as strings like `#0001`; `Unnamed: 2` is species, `Unnamed: 3/4` are Type1/Type2.
  * Same trailing form-label rows pattern (e.g., Alolan Form, Galarian Form, Hisuian Form, Therian Forme, Origin Forme) with no types on those rows; they belong to the last type row above.
  * This sheet does not include Mega typings (e.g., Mega Charizard X’s Dragon typing is not present).

* ListOfPokémonByExperienceType.csv
  * Columns: `#` (float), `Pokémon`, `Experience type`. Flat, no forms. Join by `dex`.

* pokemon.json
  * Object `{ "dex": { slug -> number } }` that mixes canonical dex for base species (`bulbasaur: "1"`) and override IDs for alt/regionals starting at 2019 and going very high (e.g., `vulpix-alolan: "2037"`, `zapdos-galar: "4145"`).
  * Contains typos/inconsistencies you must compensate for before lookups: `ratatta-alolan``rattata-alolan`, `diglet-alolan``diglett-alolan`, `carsola-galar``corsola-galar`, `yanmask-galar``yamask-galar`, `mr.mime-galar``mr-mime-galar`; also *-galar entries where canon is Hisuian (e.g., `voltorb-galar` should be `voltorb-hisui`, `growlithe-galar` -> `growlithe-hisui`).

## Why your thumbnail step stalled

* This `.xlsx` doesn’t carry per-row images; only one sheet image is present. There is nothing to anchor per-row thumbnails to, so a locator based on Excel drawing anchors can’t work here.
* That cascaded into dex gaps because your pipeline likely gates catalog entries on finding a thumbnail mapping. Since most rows had no image mapping, they were marked unprocessed and gaps inflated.

Fix: decouple record creation from thumbnails. Build the full catalog from data sources alone, and treat thumbnails as an optional enrichment keyed by a deterministic `image_id`. Rename or copy images only when an external mapping exists.

## Minimal changes to your current builder

1. Don’t gate on images. Always emit a row for every stats entry (1..1025). Populate `thumbnails` only if you can derive a target path.
2. Stats parser (for `List of Pokémon by base stats.xlsx`):
   * Use header row 0. `dex = int(row['#'])` if numeric; name is `row['Unnamed: 2']`.
   * Maintain `last_stat_entry`. If `#` is NaN and all stat fields are NaN and `Unnamed: 2` is non-empty, treat `Unnamed: 2` as form label for `last_stat_entry`.
   * Emit one record per stat row with attached optional `form_label`.
3. Types parser (for `ListOfPokemonByType.xlsx`):
   * When `Generation I` is present, set `last_seen_dex = int(Ndex[1:])`.
   * A row with `Unnamed: 2` (species) and at least `Unnamed: 3` (Type1) is a type row; start `last_type_entry`.
   * A row with `Unnamed: 2` containing a form label and no types attaches to `last_type_entry` as its `form_label`.
   * Build a map keyed by `(dex, species_slug, form_slug)`; also store a base-form fallback keyed `(dex, species_slug, "")`.
4. Form normalization (shared by both parsers):
   * `Alolan Form`→`alola`, `Galarian Form`→`galar`, `Hisuian Form`→`hisui`, `Paldean Form`→`paldea`, `Origin Forme`→`origin`, `Therian Forme`→`therian`, `Incarnate Forme`→`incarnate`; `Mega <X|Y|>`→`mega`, `mega-x`, `mega-y`; strip form/forme, lowercase, `[^a-z0-9]+`→`-`.
   * `species_slug`: unicode-normalize, lowercase, strip punctuation; special-case things like `Mr. Mime`→`mr-mime`, `Farfetch'd`→`farfetchd`.
5. Join:
   * Stats = primary set. Left-join Types on `(dex, species_slug, form_slug)`; fallback to `(dex, species_slug, "")` if not found.
   * Left-join Experience on `dex` only.
6. Override IDs (`dex_extended`) using `pokemon.json`:
   * Lookup key: `species_slug` or `species_slug + '-' + form_slug` (when form present).
   * Apply a small exceptions map to fix the typos listed above before lookup.
   * If the mapped integer is ≥ 2019, set `dex_extended` to it; else leave `dex_extended = dex`.
7. Thumbnails (non-blocking):
   * Define a stable `image_id = "{dex_extended:04d}-{species_slug}{('-' + form_slug) if form_slug else ''}"`.
   * If you have an external thumbnails folder, do a best-effort rename/copy to `data/thumbnails/{image_id}.png`. If not, just emit the target file name in the catalog and leave it to a later asset step.
8. Output schema (extend your `pokemon_catalog.json` cleanly):

```
{
  "by_dex": {
    "6": {
      "dex": 6,
      "dex_extended": 6,
      "name": "Charizard",
      "species_slug": "charizard",
      "form_label": null,
      "form_slug": null,
      "display_name": "Charizard",
      "stats": { "hp":78,"attack":84,"defense":78,"sp_atk":109,"sp_def":85,"speed":100 },
      "total": 534,
      "average": 89.0,
      "types": { "type1":"Fire","type2":"Flying" },
      "exp_group": "Medium Slow",
      "thumbnails": { "default": "data/thumbnails/0006-charizard.png",
                      "forms": { "mega-x": "data/thumbnails/0006-charizard-mega-x.png" } },
      "forms_detected": ["mega-x","mega-y"],
      "form_overrides": { "alola": 2037 },
      "sources": {
        "stats": "List of Pokémon by base stats.xlsx",
        "types": "ListOfPokemonByType.xlsx",
        "experience": "ListOfPokémonByExperienceType.csv",
        "overrides": "pokemon.json"
      }
    }
  }
}
```

9. Quality gates (replace your current gaps<1025 check):
   * Gaps should be computed from stats rows only (expect none for 1..1025 given this file).
   * Log type misses where `(dex, species_slug, form_slug)` didn’t match and had to fallback.
   * Log override misses where a slug didn’t match any `pokemon.json` key (after exceptions).
   * Keep `pokemon_catalog_unprocessed_rows.json` for genuine parse errors, not “no thumbnail found”.

## One-pager you can drop into the ticket

> Goal
> Extend `debug/tools/build_pokemon_catalog.py` to build a complete consolidated catalog (stats + types + growth + optional thumbnails), using the four supplied sources. Do not gate rows on thumbnail detection.
>
> Sources
> * Stats: `List of Pokémon by base stats.xlsx` (Sheet1; headers on row 0).
> * Types: `ListOfPokemonByType.xlsx` (Sheet1; headers row 0; data row 1+).
> * Growth: `ListOfPokémonByExperienceType.csv`.
> * Overrides: `pokemon.json` (`dex` map of slug→int; alt forms ≥2019).
>
> Parsing rules
> * Stats sheet: `dex = int(row['#'])` if numeric; species name is `row['Unnamed: 2']`. A row with `#=NaN`, all stat fields `NaN`, and `Unnamed: 2` non-empty is a form-label row for the preceding stat row. Emit one record per stat row with attached optional `form_label`.
> * Types sheet: when `Generation I` has `#NNNN`, set `last_seen_dex`. A row with `Unnamed: 2` (species) and `Unnamed: 3` (Type1) is a type row; a subsequent row with `Unnamed: 2` like Alolan Form, Galarian Form, Hisuian Form, Therian Forme, Origin Forme and no types attaches as its form-label. Build a lookup keyed `(dex, species_slug, form_slug)` and also `(dex, species_slug, "")` for base fallback.
> * Form normalization: `Alolan Form`→`alola`, `Galarian`→`galar`, `Hisuian`→`hisui`, `Paldean`→`paldea`, `Origin Forme`→`origin`, `Therian Forme`→`therian`, `Incarnate Forme`→`incarnate`, `Mega X/Y`→`mega-x/mega-y`; strip form/forme, lowercase, slugify.
> * Join: Stats is primary. Left-join Types on `(dex, species_slug, form_slug)` with fallback to `(dex, species_slug, "")`. Left-join Growth on `dex`.
> * Overrides (`dex_extended`): Build key `species_slug` or `species_slug-form_slug`. Apply an exceptions map for known typos (`ratatta`→`rattata`, `diglet`→`diglett`, `carsola`→`corsola`, `yanmask`→`yamask`, `mr.mime`→`mr-mime`, and *-galar where canon is hisui for Voltorb/Growlithe). If override ≥2019, use it; else keep canonical `dex`.
> * Thumbnails (optional): Define `image_id = "{dex_extended:04d}-{species_slug}{('-' + form_slug) if form_slug else ''}"`. If a thumbnail source exists, copy/rename to `data/thumbnails/{image_id}.png`. Do not block record creation if the image is missing.
>
> Output
> * `Source/data/pokemon_catalog.json` (extend current schema): add `dex_extended`, `species_slug`, `form_slug`, `display_name`, `types`, `exp_group`, and computed `thumbnails.*` paths (even if files don’t exist yet).
> * `Source/data/thumbnails_index.json`: keep as quick lookup but decoupled from row emission.
> * Logs:
>   * `pokemon_catalog_unprocessed_rows.json` — only genuine parse errors.
>   * `pokemon_catalog_type_fallbacks.json` — places where type had to fall back from base.

## 2025-09 Updates (Implemented)

- Types: Improved typed variant + form-label capture (e.g., Vulpix → Alolan Vulpix Ice) and added knowledge overrides for Megas.
- Overrides: typo-tolerant matching against `pokemon.json` with hisui/galar swaps where needed.
- Thumbnails:
  - Decoupled catalog rows from image presence; deterministic targets by `{dexExtended}-{species}[-{form}].png`.
  - Added curated mapping workflow: `--emit-thumbnails-mapping` → edit → `--apply-thumbnails-mapping` using the Excel’s xl/media with human-approved pairs.

## Tips: Using `pokemon_catalog.json` across the app

This catalog is now the single source of truth for species metadata (names, forms, types, base stats, optional thumbnails, growth mapping). Below are practical tips for other modules (Modifiers/Items Manager, Starters, etc.).

### Loading and caching

- Use `rogueeditor.catalog.load_pokemon_catalog()` once per session/dialog and keep a reference (avoid re-reading on every event).
- Navigate via `by_dex[str(dex)]` for base entries. Use `entry.forms[form_slug]` for form-specific overrides (types, thumbnail, display_name).
- For UI color coding of types, use `rogueeditor.catalog.load_type_colors()`; never hardcode.

### Resolving species, forms, and types

- Prefer dexId/speciesId from the slot: `by_dex[str(dex)]`.
- If you need form-aware typing, detect a form slug from the mon (e.g., fields like `form`, `formName`, booleans like `isAlolan`, fallback to parenthesized nickname), then use `entry.forms[form_slug].types` else `entry.types`.
- Defensive matchups: load the matrix via `load_type_matchup_matrix()`; the matrix is defensive (columns=defense, rows=attack). For dual types multiply type1×type2 per attack type to get final effectiveness.

### Base stats, names, and thumbnails

- Base stats: prefer `entry.stats` → a dict `{ hp, attack, defense, sp_atk, sp_def, speed }`. Fallback to legacy base stats only if absent.
- Display name: `entry.name`. For forms, `entry.forms[form_slug].display_name` (e.g., “Mega X”, “Speed Forme”). Compose as `f"{name} ({display_name})"` for UI.
- Thumbnails:
  - Base: `entry.thumbnails.default`
  - Form: `entry.forms[form_slug].thumbnail`
  - Paths are deterministic even if assets are missing; show a placeholder if not present on disk.

### Growth group

- For EXP↔Level logic, load the growth index map once via `rogueeditor.catalog.load_growth_group_map()` and index `dex → growthIndex`.
- Derive level from EXP: `level_from_exp(growthIndex, exp)`; EXP breakpoint for a target level: `exp_for_level(growthIndex, level)`.

### Dex overrides and assets

- Some forms use extended dex IDs (≥2019). For asset naming or sorting, prefer `entry.dex_extended` for base and `form.dex_extended` for forms; otherwise use canonical `dex`.

### Examples and suggested uses

- Modifiers / Items Manager
  - When showing a mon, fetch species (`entry.name`) and form display name, render type chips with `load_type_colors()`.
  - Optional: show a compact defensive chart by reusing `load_type_matchup_matrix()` and the multiplicative rule.
  - Full Restore/PP flows can use catalog stats to compute max HP when server `stats` are missing.

- Starters
  - Provide a small form selector that maps to form slugs (alola/galar/hisui/mega, etc.) and render the preview with form-aware types.
  - When writing starter templates, default growth group and base stats from catalog; thumbnails from `thumbnails.default`/form thumbnail when present.

- Items suggestions (future)
  - Use defensive matchups to surface recommended held items (e.g., type-resist berries) based on the most common weaknesses in the team.

### Defensive notes / limitations

- Defensive chart in the GUI is a pure type defense view. It ignores abilities, passives, held items, and special forms like Mega/Tera (unless the form itself has different types in the catalog).
- If the save data later includes canonical form fields or Tera typings, wire those into the form detection before lookup.

>
> Acceptance checks
> * No dex gaps for 1..1025 in stats-derived rows.
> * Rattata yields base + `alola` with different types.
> * Deterministic slugging across runs.

## Ranked options
1. Decouple thumbnails + implement parsers and joins now (recommended, fastest path).
3. Replace `pokemon.json` with a clean internal ID scheme and/or sanitize it once.

Recommendation: Option 1 now. Wrap type resolution behind a function so Option 2 can be swapped in later.

## What I still need or will assume
* If you want `dex_extended` from `species-id.ts` instead of `pokemon.json`, give me the path and key format; I’ll add a small adapter and keep `pokemon.json` as a fallback.
* If you want correct Mega typings, provide a source or accept base-type inheritance for now.
* If you do have a thumbnails source folder (even messy), point to it; I’ll implement a non-blocking best-effort renamer keyed by the `image_id`.

If you supply those paths, I’ll fold them into the builder spec without changing the rest of your pipeline.
