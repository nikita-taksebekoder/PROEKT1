# remove_esp32_all.ps1
param()
$owner='nikita-taksebekoder'
$skip='PROEKT1'
$timestamp=(Get-Date -Format 'yyyyMMdd_HHmmss')
$repos = (gh repo list $owner --limit 500 --json name -q '.[].name') -split "\r?\n" | Where-Object { $_ -and $_ -ne '' }
Write-Host 'Found repos:' ($repos -join ', ')
$results = @()
foreach ($r in $repos) {
  if ($r -eq $skip) {
    Write-Host "Skipping $r"
    $results += [pscustomobject]@{repo=$r; status='skipped'}
    continue
  }
  $tmp = Join-Path $env:TEMP "reorg_${owner}_$r"
  if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
  Write-Host ("Cloning {0} -> {1}" -f $r, $tmp)
  gh repo clone "$owner/$r" $tmp -- --depth 1 2>&1 | Out-Null
  if (-not (Test-Path $tmp)) {
    Write-Host ("Clone failed for {0}" -f $r)
    $results += [pscustomobject]@{repo=$r; status='clone-failed'}
    continue
  }
  Push-Location $tmp
  try {
    git rev-parse --verify main 2>$null
    if ($LASTEXITCODE -ne 0) {
      Write-Host ("No main branch for {0}, trying master" -f $r)
      git rev-parse --verify master 2>$null
      if ($LASTEXITCODE -eq 0) { git checkout master } else { git checkout -b main }
    } else { git checkout main }
  } catch {
    git checkout -b main
  }
  $backupBranch = "before-remove-esp32-$timestamp"
  git branch "$backupBranch"
  Write-Host ("Created backup branch {0}" -f $backupBranch)
  $toRemove = New-Object System.Collections.Generic.List[string]
  $patterns = @('main','components','managed_components','esp-idf','partition_table','bootloader-prefix','build','sdkconfig*','sdkconfig','sdkconfig.defaults*','partitions.csv','PROEKT1.py','.project','.cproject','.settings','.clangd','.clang-format','CMakeLists.txt')
  foreach ($p in $patterns) {
    try { $matches = Get-ChildItem -Path . -Force -Recurse -ErrorAction SilentlyContinue -Filter $p | Select-Object -ExpandProperty FullName -ErrorAction SilentlyContinue } catch { $matches = @() }
    if ($matches) { foreach ($m in $matches) { $rel = (Resolve-Path -Relative $m) ; if (-not $toRemove.Contains($rel)) { $toRemove.Add($rel) } } }
    else { if (Test-Path $p) { if (-not $toRemove.Contains($p)) { $toRemove.Add($p) } } }
  }
  try { $bins = Get-ChildItem -Path . -Recurse -Include '*.elf','*.bin','*.map' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName -ErrorAction SilentlyContinue } catch { $bins = @() }
  foreach ($b in $bins) { $rel = (Resolve-Path -Relative $b); if (-not $toRemove.Contains($rel)) { $toRemove.Add($rel) } }
  $list = $toRemove | Sort-Object -Unique
  if (-not $list -or $list.Count -eq 0) {
    Write-Host ("No ESP32 patterns found in {0}, skipping" -f $r)
    $results += [pscustomobject]@{repo=$r; status='no-match'}
    Pop-Location; Remove-Item -Recurse -Force $tmp; continue
  }
  Write-Host ("Will remove from {0}:" -f $r)
  $list | ForEach-Object { Write-Host " - $_" }
  $hadError = $false
  foreach ($p in $list) {
    if (Test-Path $p) {
      git rm -r --cached --ignore-unmatch "$p" 2>$null
      git rm -r -- "$p" 2>$null
    }
  }
  $giPath = Join-Path $tmp '.gitignore'
  $giContent = @(
    '# Auto-generated: ignore build/artifacts',
    'build/',
    '*.elf',
    '*.bin',
    '*.map',
    '.vscode/',
    '.vs/',
    '.pio/',
    '/sdkconfig',
    '/sdkconfig.*'
  ) -join "`n"
  if (Test-Path $giPath) {
    $existing = Get-Content $giPath -Raw
    if ($existing -notlike '*Auto-generated: ignore build/artifacts*') { Add-Content -Path $giPath -Value "`n$giContent" }
  } else { Set-Content -Path $giPath -Value $giContent }
  git add -A
  if ((git status --porcelain) -eq '') {
    Write-Host ("No changes after removal in {0}" -f $r)
    $results += [pscustomobject]@{repo=$r; status='no-changes'}
    Pop-Location; Remove-Item -Recurse -Force $tmp; continue
  }
  try { git commit -m "Remove ESP32-related files (moved to PROEKT1); add .gitignore" } catch { Write-Host ("Commit failed for {0}" -f $r); $hadError = $true }
  if (-not $hadError) {
    Write-Host ("Pushing changes to origin/main for {0}" -f $r)
    git push origin HEAD:main 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { $results += [pscustomobject]@{repo=$r; status='pushed'; removed=$list.Count} } else { $results += [pscustomobject]@{repo=$r; status='push-failed'} }
  }
  Pop-Location; Remove-Item -Recurse -Force $tmp; Start-Sleep -Milliseconds 500
}
Write-Host "`nSummary:"; $results | Format-Table -AutoSize
$results | ConvertTo-Json -Depth 5 | Out-File "$env:TEMP/remove_esp32_results.json"
Write-Host "Detailed JSON written to $env:TEMP/remove_esp32_results.json"
