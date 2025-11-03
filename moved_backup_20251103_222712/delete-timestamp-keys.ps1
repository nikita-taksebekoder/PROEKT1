param(
  [string]$WorkerUrl = 'https://yclients-proxy-to-tilda.rookman13.workers.dev',
  [string]$AdminKey = '464FRq3MMbudGBKrjTFDT8YMIolhl5zlJ70EbDfSqYylQ5wYuQ83pcA5OQiAvaIy',
  [switch]$Apply
)

Write-Host "Worker: $WorkerUrl"
Write-Host "Mode: " + ($Apply.IsPresent ? 'APPLY (will delete keys)' : 'DRY-RUN (no changes)')

# 1) fetch all keys
Write-Host 'Fetching keys from /admin/list-ids...'
try {
  $list = Invoke-RestMethod -Method Get -Uri "$WorkerUrl/admin/list-ids" -Headers @{ 'X-Admin-Key' = $AdminKey } -ErrorAction Stop
} catch {
  Write-Error "Failed to fetch list-ids: $($_.Exception.Message)"
  exit 1
}

if (-not $list.keys) { Write-Host 'No keys returned.'; exit 0 }

$allKeys = $list.keys
Write-Host "Total keys: $($allKeys.Count)"

# 2) decide which keys look like timestamp-import keys
# Pattern: keys that start with a long numeric timestamp + '-' (e.g. 1762119009053-43462321) or ping- prefixes
$tsPattern = '^[0-9]{10,}-[0-9]+'
$pingPattern = '^ping-'

$toDelete = $allKeys | Where-Object { $_ -match $tsPattern -or $_ -match $pingPattern }
$keep = $allKeys | Where-Object { -not ($_ -match $tsPattern -or $_ -match $pingPattern) }

Write-Host "Candidates to delete (count): $($toDelete.Count)"
if ($toDelete.Count -gt 0) {
  Write-Host 'Sample to-delete keys:'
  $toDelete | Select-Object -First 20 | ForEach-Object { Write-Host "  $_" }
}

# write dry-run output
$out = @{ worker = $WorkerUrl; timestamp = (Get-Date).ToString('o'); total = $allKeys.Count; to_delete = $toDelete; keep = $keep }
$jsonFile = Join-Path -Path (Get-Location) -ChildPath "delete-timestamp-keys.dryrun.$((Get-Date).ToString('yyyyMMddHHmmss')).json"
$out | ConvertTo-Json -Depth 6 | Out-File -FilePath $jsonFile -Encoding utf8
Write-Host "Dry-run report written to: $jsonFile"

if (-not $Apply.IsPresent) {
  Write-Host "DRY-RUN complete. To apply deletions run this script again with -Apply switch (careful!)."
  exit 0
}

# 3) Apply: call /admin/sync with keep list (server will delete keys not in keep)
Write-Host 'APPLY: sending keep list to /admin/sync (this will delete the candidate keys)...'
try {
  $payload = @{ ids = $keep } | ConvertTo-Json
  $resp = Invoke-RestMethod -Method Post -Uri "$WorkerUrl/admin/sync" -Headers @{ 'X-Admin-Key' = $AdminKey; 'Content-Type' = 'application/json' } -Body $payload -ErrorAction Stop
  Write-Host 'Admin sync response:'
  $resp | ConvertTo-Json -Depth 6 | Write-Host
} catch {
  Write-Error "Failed to apply admin/sync: $($_.Exception.Message)"
  exit 1
}

Write-Host 'APPLY complete.'
