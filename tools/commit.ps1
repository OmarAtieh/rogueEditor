Param(
  [string]$Remote = "origin",
  [string]$Branch = "main"
)

function Stage-And-Commit {
  param(
    [Parameter(Mandatory=$true)][string[]]$Paths,
    [Parameter(Mandatory=$true)][string]$Message,
    [string[]]$Exclude = @()
  )
  if (-not $Paths -or $Paths.Count -eq 0) { return }
  $existing = @()
  foreach ($p in $Paths) {
    $matches = git ls-files --others --modified --exclude-standard -- $p 2>$null
    if (-not $matches) { $matches = git diff --name-only -- $p 2>$null }
    if ($matches) { $existing += $matches }
  }
  $existing = $existing | Sort-Object -Unique
  if ($Exclude -and $Exclude.Count -gt 0) {
    $regex = ($Exclude | ForEach-Object { [regex]::Escape($_).Replace('\*', '.*') })
    $existing = $existing | Where-Object {
      $keep = $true
      foreach ($r in $regex) { if ($_ -match "^$r$") { $keep = $false; break } }
      $keep
    }
  }
  if ($existing.Count -gt 0) {
    Write-Host "Staging ($($existing.Count)) for: $Message" -ForegroundColor Cyan
    git add -- $existing
    git commit -m $Message
  }
}

git status --porcelain
if ($LASTEXITCODE -ne 0) { throw "Not a git repo or git not available." }

# Exclusions (do not commit thumbnails or index yet)
$exclude = @(
  "Source/data/thumbnails/*",
  "Source/data/thumbnails_index.json"
)

# Group 1: GUI modular package scaffold (common/dialogs/sections)
Stage-And-Commit -Paths @(
  "Source/gui/"
) -Message "gui: modular package scaffold and delegator" -Exclude $exclude

# Group 2: Diagnostics & healthcheck infra
Stage-And-Commit -Paths @(
  "Source/rogueeditor/logging_utils.py",
  "Source/rogueeditor/healthcheck.py"
) -Message "infra: logging + healthcheck to diagnose GUI startup" -Exclude $exclude

# Group 3: Session lifecycle updates (CLI/API/Editor/Utils)
Stage-And-Commit -Paths @(
  "Source/cli.py",
  "Source/rogueeditor/api.py",
  "Source/rogueeditor/editor.py",
  "Source/rogueeditor/utils.py"
) -Message "session: fresh csid per login; CLI/GUI plumbing" -Exclude $exclude

# Group 4: Data catalogs: base stats
Stage-And-Commit -Paths @(
  "Source/rogueeditor/base_stats.py",
  "Source/data/base_stats.json"
) -Message "data: add base stats catalog + loader" -Exclude $exclude

# Group 5: GUI startup fix and handler wiring
Stage-And-Commit -Paths @(
  "Source/gui.py"
) -Message "gui: fix startup crash; add Upload All handler" -Exclude $exclude

# Group 6: Docs/Changelog update for bugfix
Stage-And-Commit -Paths @(
  "CHANGELOG.md",
  "debug/docs/GUI_MIGRATION_PLAN.md"
) -Message "docs: postmortem for GUI startup fix; update changelog" -Exclude $exclude

# Group 7: Team Editor enhancements (Form & Visuals, EXP↔Level, status)
Stage-And-Commit -Paths @(
  "Source/gui/dialogs/team_editor.py",
  "Source/gui/sections/slots.py"
) -Message "team-editor: add Form & Visuals; EXP↔Level sync; status UX; growth rate" -Exclude $exclude

# Group 8: New catalogs and growth mapping
Stage-And-Commit -Paths @(
  "Source/rogueeditor/catalog.py",
  "Source/data/exp_tables.json",
  "Source/data/types.json",
  "Source/data/type_matrix.json",
  "Source/data/pokeballs.json",
  "Source/data/growth_map.json"
) -Message "data: exp tables/types/pokeballs/growth mapping; helpers" -Exclude $exclude

# Group 9: Team Editor plan doc
Stage-And-Commit -Paths @(
  "debug/docs/TEAM_EDITOR_ENHANCEMENTS_PLAN.md"
) -Message "docs: team editor enhancements plan and progress" -Exclude $exclude

# Any remaining changes
$remaining = git status --porcelain | % { $_.Substring(3) } | Where-Object { $_ -ne "" }
if ($remaining) {
  # Exclude known large/generated assets from the catch-all commit
  if ($exclude -and $exclude.Count -gt 0) {
    $regex = ($exclude | ForEach-Object { [regex]::Escape($_).Replace('\\*', '.*') })
    $remaining = $remaining | Where-Object {
      $keep = $true
      foreach ($r in $regex) { if ($_ -match "^$r$") { $keep = $false; break } }
      $keep
    }
  }
  if ($remaining.Count -gt 0) {
    Write-Host "Staging remaining changes..." -ForegroundColor Yellow
    git add -- $remaining
    git commit -m "misc: remaining changes"
  }
}

Write-Host "Pushing to $Remote/$Branch..." -ForegroundColor Green
git push $Remote $Branch
