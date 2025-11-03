$wk = 'https://yclients-proxy-to-tilda.rookman13.workers.dev'
$adminKey = '464FRq3MMbudGBKrjTFDT8YMIolhl5zlJ70EbDfSqYylQ5wYuQ83pcA5OQiAvaIy'

Write-Host '=== /admin/list-ids ==='
try {
  Invoke-RestMethod -Method Get -Uri "$wk/admin/list-ids" -Headers @{ 'X-Admin-Key' = $adminKey } | ConvertTo-Json -Depth 6 | Write-Host
} catch { Write-Host 'ERROR (list-ids):' $_.Exception.Message }

Write-Host "`n=== /events?limit=20 (headers + body) ==="
try {
  $resp = Invoke-WebRequest -Method Get -Uri "$wk/events?limit=20" -UseBasicParsing -ErrorAction Stop
  Write-Host '--- Response headers ---'
  $resp.Headers.GetEnumerator() | ForEach-Object { Write-Host "$($_.Name): $($_.Value)" }
  Write-Host '--- Body ---'
  $resp.Content | ConvertFrom-Json | ConvertTo-Json -Depth 6 | Write-Host
} catch { Write-Host 'ERROR (events):' $_.Exception.Message }

Write-Host "`n=== /event/test-1 ==="
try {
  Invoke-RestMethod -Method Get -Uri "$wk/event/test-1" -ErrorAction Stop | ConvertTo-Json -Depth 8 | Write-Host
} catch { Write-Host 'ERROR (event/test-1):' $_.Exception.Message }