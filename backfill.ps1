<#
.SYNOPSIS
  Backfill script for YCLIENTS comments -> Cloudflare Worker admin/import

.DESCRIPTION
  Пагинация API YCLIENTS, преобразование комментариев в payload и пакетная
  отправка в endpoint /admin/import защищённый X-Admin-Key.

.PARAMETER IngestUrl
  URL воркера (например https://yclients-proxy-to-tilda.rookman13.workers.dev)
.PARAMETER AdminKey
  Заголовок X-Admin-Key для admin/import
.PARAMETER PartnerToken
  YCLIENTS partner token (Bearer)
.PARAMETER UserToken
  YCLIENTS user token (optional)
.PARAMETER CompanyId
  company_id для запроса комментариев (можно задать через env YCLIENTS_COMPANY_ID)
.PARAMETER PageSize
  Количество комментариев на страницу при запросе к YCLIENTS (max ~100)
.PARAMETER BatchSize
  Сколько записей отправлять за 1 POST в /admin/import
.PARAMETER SyncDeleteMissing
  Если $true — после импорта отправляет список ids в /admin/sync чтобы удалить устаревшие
.EXAMPLE
  .\backfill.ps1 -IngestUrl 'https://...workers.dev' -AdminKey 'secret' -PartnerToken 'pt' -CompanyId 123
#>

[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$IngestUrl,
  [string]$AdminKey,
  [string]$PartnerToken,
  [string]$UserToken,
  [string]$CompanyId = $env:YCLIENTS_COMPANY_ID,
  [int]$PageSize = 100,
  [int]$BatchSize = 5,
  [switch]$SyncDeleteMissing,
  [switch]$InsecureSkipSsl
)

if (-not $AdminKey) { Write-Host 'Warning: AdminKey not provided; /admin endpoints will be unauthorized' }
if (-not $PartnerToken) { Write-Host 'Warning: PartnerToken not provided; YCLIENTS requests will fail' }
if (-not $CompanyId) { Write-Error 'CompanyId is required (param or env YCLIENTS_COMPANY_ID)'; exit 2 }

function Invoke-YClientsGet {
  param($url)
  # Try multiple header formats to accommodate YCLIENTS requirements. Mask tokens in logs.
  $accept = 'application/vnd.yclients.v2+json'
  $attemptHeaders = @()

  # 1) Authorization: Bearer <partner>
  if ($PartnerToken) {
    $h = @{ 'Accept' = $accept; 'Authorization' = "Bearer $PartnerToken" }
    $attemptHeaders += $h
  } else {
    $attemptHeaders += @{ 'Accept' = $accept }
  }

  # 2) Authorization: Bearer <partner> + X-User-Token: <user> (common pattern)
  if ($PartnerToken -and $UserToken) {
    $attemptHeaders += @{ 'Accept' = $accept; 'Authorization' = "Bearer $PartnerToken"; 'X-User-Token' = $UserToken }
  }

  # 3) Authorization: Bearer <partner>, User <user> (legacy/combined) - keep as fallback
  if ($PartnerToken -and $UserToken) {
    $attemptHeaders += @{ 'Accept' = $accept; 'Authorization' = "Bearer $PartnerToken, User $UserToken" }
  }

  # 4) User only (unlikely) - try as last resort
  if ($UserToken) {
    $attemptHeaders += @{ 'Accept' = $accept; 'Authorization' = "User $UserToken" }
  }

  if ($InsecureSkipSsl) { [System.Net.ServicePointManager]::ServerCertificateValidationCallback = { $true } }

  $lastErr = $null
  foreach ($hdr in $attemptHeaders) {
    # Log attempt with masked tokens
    $mask = {
      param($s)
      if (-not $s) { return '' }
      return ($s -replace ".{4}.*(.{4})$","****$1")
    }
    $maskedAuth = $null
    if ($hdr.ContainsKey('Authorization')) { $maskedAuth = & $mask $hdr['Authorization'] }
    $maskedXUser = $null
    if ($hdr.ContainsKey('X-User-Token')) { $maskedXUser = & $mask $hdr['X-User-Token'] }
    Write-Host "Trying YCLIENTS GET with Authorization='$maskedAuth' X-User-Token='$maskedXUser'"
    try {
      $r = Invoke-RestMethod -Uri $url -Headers $hdr -Method Get -ErrorAction Stop
      return $r
    } catch {
      $lastErr = $_.Exception.Message
      Write-Host "Attempt failed: $lastErr"
    }
  }

  Write-Error "YCLIENTS fetch failed after ${($attemptHeaders.Count)} attempts: $lastErr"
  return $null
}

function Post-AdminImport {
  param($payload)
  $uri = "$IngestUrl/admin/import"
  $headers = @{ 'X-Admin-Key' = $AdminKey; 'Content-Type' = 'application/json' }
  try {
    $body = ($payload | ConvertTo-Json -Depth 6)
    $r = Invoke-RestMethod -Uri $uri -Method Post -Headers $headers -Body $body -ErrorAction Stop
    return $r
  } catch {
    Write-Error "Import POST failed: $($_.Exception.Message)"
    return $null
  }
}

# collect existing ids from ingress to avoid re-import (optional optimization)
$existingIds = @{}
if ($AdminKey) {
  try {
    $listUri = "$IngestUrl/admin/list-ids"
    $h = @{ 'X-Admin-Key' = $AdminKey }
    $r = Invoke-RestMethod -Uri $listUri -Method Get -Headers $h -ErrorAction Stop
    if ($r.keys) { foreach ($k in $r.keys) { $existingIds[$k] = $true } }
    Write-Host "Fetched $($r.keys.Count) existing ids from admin/list-ids"
  } catch {
    Write-Host "Could not fetch existing ids: $($_.Exception.Message) — proceeding without prefilter"
  }
}

$allEvents = @()
$page = 1
while ($true) {
  $target = "https://api.yclients.com/api/v1/comments/$CompanyId/" + "?page=$page&count=$PageSize"
  Write-Host "Fetching page $page..."
  $resp = Invoke-YClientsGet -url $target
  if (-not $resp) { break }
  # YCLIENTS returns array or object depending on API; try to find items
  $items = @()
  if ($resp -is [System.Collections.IEnumerable]) { $items = $resp } elseif ($resp.comments) { $items = $resp.comments } else { $items = @($resp) }
  if ($items.Count -eq 0) { break }
  foreach ($c in $items) {
    # map to worker's expected payload — adjust mapping if necessary
    $evt = [PSCustomObject]@{
      event = 'comment.created'
      data = [PSCustomObject]@{
        id = ($c.id -as [string])
        text = $c.text
        date = $c.date
        author = $c.author
        raw = $c
      }
    }
    $allEvents += $evt
  }
  Write-Host "Collected $($allEvents.Count) total events so far"
  # pagination stop condition — try to detect based on response size
  if ($items.Count -lt $PageSize) { break }
  $page++
}

if ($allEvents.Count -eq 0) { Write-Host 'No events found; exiting'; exit 0 }

# filter out existing ids if we fetched them
if ($existingIds.Count -gt 0) {
  $toImport = $allEvents | Where-Object { -not $existingIds.ContainsKey($_.data.id) }
  Write-Host "After filtering existing ids: $($toImport.Count) to import"
} else {
  $toImport = $allEvents
}

# send in batches
$batches = [System.Collections.ArrayList]::new()
for ($i=0; $i -lt $toImport.Count; $i += $BatchSize) {
  $end = [Math]::Min($i+$BatchSize-1, $toImport.Count-1)
  $slice = $toImport[$i..$end]
  $batches.Add($slice) | Out-Null
}

$importedIds = @()
$batchIndex = 0
foreach ($batch in $batches) {
  $batchIndex++
  Write-Host "Importing batch $batchIndex of $($batches.Count) — $($batch.Count) items"
  $resp = Post-AdminImport -payload $batch
  if ($resp -and $resp.results) {
    foreach ($r in $resp.results) {
      if ($r.ok -eq $true -and $r.id) { $importedIds += $r.id }
    }
    Write-Host "Batch result: imported $($resp.imported)"
  } else {
    Write-Host "Batch import returned no result or failed"
  }
}

if ($SyncDeleteMissing -and $AdminKey) {
  Write-Host "SyncDeleteMissing requested — sending full id list to /admin/sync"
  $syncUri = "$IngestUrl/admin/sync"
  $h = @{ 'X-Admin-Key' = $AdminKey; 'Content-Type' = 'application/json' }
  $body = @{ ids = $allEvents | ForEach-Object { $_.data.id } } | ConvertTo-Json -Depth 4
  try {
    $r = Invoke-RestMethod -Uri $syncUri -Method Post -Headers $h -Body $body -ErrorAction Stop
    Write-Host "Sync response: $($r | ConvertTo-Json -Depth 3)"
  } catch {
    Write-Error "Sync POST failed: $($_.Exception.Message)"
  }
}

Write-Host "Done. Imported ids count: $($importedIds.Count)"
