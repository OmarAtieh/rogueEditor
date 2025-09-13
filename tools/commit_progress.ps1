Param(
  [switch]$Push
)

Write-Host "== rogueEditor commit helper =="

function GitSafeAdd($paths) {
  foreach ($p in $paths) {
    if (Test-Path $p) { git add $p }
  }
}

# 1) Clean up legacy thumbnails matching image###.png or image####.png
$thumbDir = "Source/data/thumbnails"
if (Test-Path $thumbDir) {
  Get-ChildItem $thumbDir -File | Where-Object { $_.Name -match '^image\d{3,4}\.png$' } | ForEach-Object {
    git rm --cached --force -- $_.FullName 2>$null | Out-Null
    Remove-Item -Force $_.FullName -ErrorAction SilentlyContinue
    Write-Host "Removed legacy thumbnail:" $_.Name
  }
}

# 2) GUI + catalog changes
$guiFiles = @(
  "Source/gui/dialogs/team_editor.py",
  "Source/rogueeditor/catalog.py"
)
GitSafeAdd $guiFiles
if ((git diff --cached --name-only | Select-String -Quiet "team_editor.py|rogueeditor/catalog.py")) {
  git commit -m "gui(team-editor): form-aware type matchups, trainer summary, basics header; catalog helpers (pokemon_catalog, type colors)"
}

# 3) Data builder changes (catalog/thumbnails workflow)
$builder = "debug/tools/build_pokemon_catalog.py"
GitSafeAdd @($builder)
if ((git diff --cached --name-only | Select-String -Quiet "build_pokemon_catalog.py")) {
  git commit -m "data: builder form-aware types, knowledge overrides, curated thumbnails mapping"
}

# 4) Docs: CHANGELOG, README, plans
$docFiles = @(
  "CHANGELOG.md",
  "README.md",
  "debug/docs/TEAM_EDITOR_ENHANCEMENTS_PLAN.md",
  "debug/docs/POKEMON_DATA_CONSOLIDATION_PLAN.md"
)
GitSafeAdd $docFiles
if ((git diff --cached --name-only | Select-String -Quiet "CHANGELOG.md|README.md|TEAM_EDITOR_ENHANCEMENTS_PLAN.md|POKEMON_DATA_CONSOLIDATION_PLAN.md")) {
  git commit -m "docs: changelog, readme, team editor plan, data consolidation updates"
}

# 5) Avoid staging new thumbnails (safety): unstage any under thumbnails, if staged
if (Test-Path $thumbDir) {
  git reset HEAD -- $thumbDir 2>$null | Out-Null
}

if ($Push) {
  git push
}

Write-Host "Done. Review 'git log --oneline' for grouped commits."

