param(
    [string]$TargetPath = 'D:\Дизайн\2018 Бариста школа\6. Кастом для Tilda',
    [switch]$DryRun
)

# LIST OF CANDIDATES TO MOVE (adjust if needed)
$items = @(
    'proxy-worker.js',
    'worker.js',
    'Вставка для Tilda — Отзывы.html',
    'tilda_brand_slider_insert.html',
    'README.backfill.md',
    'README.md',
    'backfill.ps1',
    'check-duplicates.ps1',
    'check-worker.ps1',
    'delete-timestamp-keys.ps1',
    'clean-empty-reviews.js',
    'payload.json',
    'test-import-5.json',
    'yc-headers-output.txt',
    'yc-test-headers.ps1',
    'tilda_brand_slider_insert.html',
    'backfill.ps1',
    'scripts',
    '.github',
    '.wrangler',
    'wrangler.toml'
)

$cwd = (Get-Location).ProviderPath
Write-Host "Working directory: $cwd"
Write-Host "Target directory: $TargetPath"

# normalize target
$targetFull = [System.IO.Path]::GetFullPath($TargetPath)

if (-not $DryRun) {
    if (-not (Test-Path -Path $targetFull)) {
        Write-Host "Target does not exist. Creating: $targetFull"
        New-Item -ItemType Directory -Path $targetFull -Force | Out-Null
    }
}

# prepare backup folder inside current directory
$ts = (Get-Date).ToString('yyyyMMdd_HHmmss')
$backupDir = Join-Path -Path $cwd -ChildPath "moved_backup_$ts"

if (-not $DryRun) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
    Write-Host "Backup directory created: $backupDir"
} else {
    Write-Host "DRY RUN: no directories will be created or modified"
}

$actions = @()
foreach ($name in $items) {
    $source = Join-Path -Path $cwd -ChildPath $name
    if (Test-Path -Path $source) {
        $dest = Join-Path -Path $targetFull -ChildPath $name
        $actions += [PSCustomObject]@{ Source = $source; Destination = $dest }
    } else {
        Write-Host "Skip (not found): $name"
    }
}

if ($actions.Count -eq 0) {
    Write-Host "No candidate files or directories found to move. Nothing to do."
    return
}

Write-Host "The following items will be moved:" -ForegroundColor Cyan
$actions | Format-Table -AutoSize

if ($DryRun) { return }

# Confirm
$ok = Read-Host "Proceed with backup+move? Type YES to continue"
if ($ok -ne 'YES') { Write-Host 'Aborted by user.'; return }

# Copy to backup then move
foreach ($a in $actions) {
    try {
        $src = $a.Source
        $dst = $a.Destination
        $backupTarget = Join-Path -Path $backupDir -ChildPath (Split-Path -Path $src -Leaf)
        Write-Host "Backing up $src -> $backupTarget"
        Copy-Item -Path $src -Destination $backupTarget -Recurse -Force
        Write-Host "Moving $src -> $dst"
        Move-Item -Path $src -Destination $dst -Force
    } catch {
        Write-Warning "Failed to move $($a.Source): $($_.Exception.Message)"
    }
}

Write-Host "Move complete. Backup of moved items is in: $backupDir" -ForegroundColor Green
Write-Host "If some items are directories, their contents have been moved as well."
