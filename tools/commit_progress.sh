#!/usr/bin/env bash
set -euo pipefail

PUSH=false
if [[ ${1:-} == "--push" ]]; then PUSH=true; fi

echo "== rogueEditor commit helper =="

git_safe_add() {
  for p in "$@"; do
    [[ -e "$p" ]] && git add "$p" || true
  done
}

# 1) Clean up legacy thumbnails matching image###.png or image####.png
thumbDir="Source/data/thumbnails"
if [[ -d "$thumbDir" ]]; then
  while IFS= read -r -d '' f; do
    git rm --cached -f "$f" >/dev/null 2>&1 || true
    rm -f "$f"
    echo "Removed legacy thumbnail: $(basename "$f")"
  done < <(find "$thumbDir" -maxdepth 1 -type f -regextype posix-extended -regex ".*/image[0-9]{3,4}\.png" -print0)
fi

# 2) GUI + catalog changes
git_safe_add Source/gui/dialogs/team_editor.py Source/rogueeditor/catalog.py
if git diff --cached --name-only | grep -Eq "team_editor\.py|rogueeditor/catalog\.py"; then
  git commit -m "gui(team-editor): form-aware type matchups, trainer summary, basics header; catalog helpers (pokemon_catalog, type colors)"
fi

# 3) Data builder changes
git_safe_add debug/tools/build_pokemon_catalog.py
if git diff --cached --name-only | grep -q "build_pokemon_catalog\.py"; then
  git commit -m "data: builder form-aware types, knowledge overrides, curated thumbnails mapping"
fi

# 4) Docs
git_safe_add CHANGELOG.md README.md debug/docs/TEAM_EDITOR_ENHANCEMENTS_PLAN.md debug/docs/POKEMON_DATA_CONSOLIDATION_PLAN.md
if git diff --cached --name-only | grep -Eiq "CHANGELOG\.md|README\.md|TEAM_EDITOR_ENHANCEMENTS_PLAN\.md|POKEMON_DATA_CONSOLIDATION_PLAN\.md"; then
  git commit -m "docs: changelog, readme, team editor plan, data consolidation updates"
fi

# 5) Ensure no new thumbnails are staged
if [[ -d "$thumbDir" ]]; then
  git reset HEAD -- "$thumbDir" >/dev/null 2>&1 || true
fi

if $PUSH; then
  git push
fi

echo "Done. Review commits with: git log --oneline"

