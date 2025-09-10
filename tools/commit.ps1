Param(
  [string]$Remote = "origin",
  [string]$Branch = "main"
)

function Stage-And-Commit($Paths, $Message) {
  if (-not $Paths -or $Paths.Count -eq 0) { return }
  $existing = @()
  foreach ($p in $Paths) {
    $matches = git ls-files --others --modified --exclude-standard -- $p 2>$null
    if (-not $matches) { $matches = git diff --name-only -- $p 2>$null }
    if ($matches) { $existing += $matches }
  }
  $existing = $existing | Sort-Object -Unique
  if ($existing.Count -gt 0) {
    Write-Host "Staging ($($existing.Count)) for: $Message" -ForegroundColor Cyan
    git add -- $existing
    git commit -m $Message
  }
}

git status --porcelain
if ($LASTEXITCODE -ne 0) { throw "Not a git repo or git not available." }

# Group 1: GUI Starters + analysis dialogs
Stage-And-Commit @("Source/gui.py") "gui: starters picker, analysis popups, modifiers analyzer"

# Group 2: Docs/Changelog
Stage-And-Commit @("CHANGELOG.md", "README.md") "docs: update changelog and docs for GUI changes"

# Group 3: Debug/tests (if any incidental updates)
Stage-And-Commit @("debug/*") "debug: sync tests/logs/docs"

# Group 4: Other source changes
Stage-And-Commit @("Source/rogueeditor/*", "Source/data/*", "Source/cli.py", "Source/RogueEditor.py") "src: ancillary updates"

# Any remaining changes
$remaining = git status --porcelain | % { $_.Substring(3) } | Where-Object { $_ -ne "" }
if ($remaining) {
  Write-Host "Staging remaining changes..." -ForegroundColor Yellow
  git add -A
  git commit -m "misc: remaining changes"
}

Write-Host "Pushing to $Remote/$Branch..." -ForegroundColor Green
git push $Remote $Branch

