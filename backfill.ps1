<#
SYNOPSIS
  Backfill script for YCLIENTS comments -> Cloudflare Worker admin/import

DESCRIPTION
  Пагинация API YCLIENTS, преобразование комментариев в payload и пакетная
  отправка в endpoint /admin/import защищённый X-Admin-Key.

PARAMETER IngestUrl
  URL воркера (например https://yclients-proxy-to-tilda.rookman13.workers.dev)
PARAMETER AdminKey
  Заголовок X-Admin-Key для admin/import
PARAMETER PartnerToken
  YCLIENTS partner token (Bearer)
PARAMETER UserToken
  YCLIENTS user token (optional)
PARAMETER CompanyId
  company_id для запроса комментариев (можно задать через env YCLIENTS_COMPANY_ID)
PARAMETER PageSize
  Количество комментариев на страницу при запросе к YCLIENTS (max ~100)
PARAMETER BatchSize
  Сколько записей отправлять за 1 POST в /admin/import
PARAMETER SyncDeleteMissing
  Если $true — после импорта отправляет список ids в /admin/sync чтобы удалить устаревшие
EXAMPLE
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
  [int]$MaxPages = 0,
  [bool]$OnlyReviews = $true,
  [switch]$ServerSideRating,
  [switch]$DryRun,
  [switch]$SyncDeleteMissing,
  [switch]$VerboseAuthTests,
  [switch]$InsecureSkipSsl
)

# Fallback to environment variables when explicit params are not provided.
# This allows running the script with environment-configured tokens without
# repeating them on the command line.
if (-not $PartnerToken) { $PartnerToken = $env:YCLIENTS_PARTNER_TOKEN }
if (-not $UserToken)   { $UserToken   = $env:YCLIENTS_USER_TOKEN }
if (-not $CompanyId)   { $CompanyId   = $env:YCLIENTS_COMPANY_ID }

# Trim tokens/keys to remove accidental whitespace/newlines from env/secret values
if ($PartnerToken) { $PartnerToken = $PartnerToken.Trim() ; $PartnerToken = $PartnerToken.Trim("'", '"') }
if ($UserToken)    { $UserToken    = $UserToken.Trim()    ; $UserToken    = $UserToken.Trim("'", '"') }
if ($CompanyId)    { $CompanyId    = $CompanyId.Trim()    ; $CompanyId    = $CompanyId.Trim("'", '"') }
if ($AdminKey)     { $AdminKey     = $AdminKey.Trim()     ; $AdminKey     = $AdminKey.Trim("'", '"') }

if (-not $AdminKey) { Write-Output 'Warning: AdminKey not provided; /admin endpoints will be unauthorized' }
if (-not $PartnerToken) { Write-Output 'Warning: PartnerToken not provided; YCLIENTS requests will fail' }
if (-not $CompanyId) { Write-Error 'CompanyId is required (param or env YCLIENTS_COMPANY_ID)'; exit 2 }

# Mark parameters as used for static analysis (they are referenced elsewhere)
[void]$UserToken; [void]$VerboseAuthTests; [void]$InsecureSkipSsl

function Invoke-YClientsGet {
  param($url)
  # Use HttpClient and send the documented Authorization header first: "Bearer <partner>, User <user>"
  $accept = 'application/vnd.yclients.v2+json'

  # Prepare HttpClient with optional insecure SSL skip
  $handler = New-Object System.Net.Http.HttpClientHandler
  if ($InsecureSkipSsl) {
    # simplify callback signature to avoid unused parameter warnings
    $handler.ServerCertificateCustomValidationCallback = { return $true }
  }
  $client = New-Object System.Net.Http.HttpClient($handler)

  # helper to mask tokens
  $mask = { param($s) if (-not $s) { return '' } return ($s -replace ".{4}.*(.{4})$","****$1") }

  $attempts = @()
  # Try multiple reasonable auth forms (combined, partner+X-User-Token, partner-only).
  # 1) Combined single Authorization header (works for many endpoints):
  if ($PartnerToken -and $UserToken) {
    $attempts += @{ 'Authorization' = "Bearer $PartnerToken, User $UserToken"; 'Accept' = $accept }
  }
  # 2) Partner in Authorization + X-User-Token header (alternative form):
  if ($PartnerToken -and $UserToken) {
    $attempts += @{ 'Authorization' = "Bearer $PartnerToken"; 'X-User-Token' = $UserToken; 'Accept' = $accept }
  }
  # 3) Partner-only Bearer (fallback):
  if ($PartnerToken) {
    $attempts += @{ 'Authorization' = "Bearer $PartnerToken"; 'Accept' = $accept }
  }

  $lastErr = $null
  $idx = 0
  foreach ($hdr in $attempts) {
  $idx++
  $display = ($hdr.Keys | ForEach-Object { "{0}='{1}'" -f $_, (& $mask $hdr[$_]) }) -join ', '
  if ($VerboseAuthTests) { Write-Output ("Attempt #{0}: Headers -> {1}" -f $idx, $display) } else { Write-Output ("Attempt #{0}: {1}" -f $idx, $display) }

    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $url)
    foreach ($k in $hdr.Keys) {
      $v = $hdr[$k]
      # Add header without validation to allow comma-separated Authorization value
      $null = $req.Headers.TryAddWithoutValidation($k, $v)
    }

    try {
      $resp = $client.SendAsync($req).Result
      $code = [int]$resp.StatusCode
      $body = $resp.Content.ReadAsStringAsync().Result
      if ($code -ge 200 -and $code -lt 300) {
        try { return ($body | ConvertFrom-Json) } catch { return $body }
      } else {
        Write-Output "Attempt failed: HTTP $code - $body"
        $lastErr = "HTTP $code - $body"
        if ($VerboseAuthTests) {
          Write-Output "--- Debug: Failed attempt #$idx ---"
          Write-Output "Request Headers: $display"
          Write-Output "HTTP Status: $code"
          Write-Output "Response body:`n$body`n"
        }
        if ($code -eq 401) {
          Write-Error "YCLIENTS returned 401 Unauthorized. Masked tokens: $display"
        }
      }
    } catch {
      $ex = $_.Exception
      $lastErr = $ex.Message
      if ($VerboseAuthTests) {
        Write-Output "--- Debug: Exception on attempt #$idx ---"
        Write-Output "Request Headers: $display"
        Write-Output "Exception: $($ex.ToString())"
        try {
          if ($ex.Response -and $ex.Response.Content) {
            $respBody = $ex.Response.Content.ReadAsStringAsync().Result
            Write-Output "Exception response body:`n$respBody`n"
          }
        } catch {
          # Log failure to read exception response body for diagnostics
          Write-Verbose ("Failed to read exception response body: {0}" -f $_.Exception.Message)
        }
      } else {
        Write-Output "Attempt exception: $lastErr"
      }
    }
  }

  Write-Error "YCLIENTS fetch failed after ${($attempts.Count)} attempts: $lastErr"
  return $null
}

function Invoke-AdminImport {
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
  Write-Output "Fetched $($r.keys.Count) existing ids from admin/list-ids"
  } catch {
  Write-Output "Could not fetch existing ids: $($_.Exception.Message) — proceeding without prefilter"
  }
}

$allEvents = @()
$scannedItems = 0
function Process-And-MapItems {
  param($items)
  foreach ($c in $items) {
    # determine whether this item qualifies as a review (server-side may already ensure rating)
    $hasRating = ($c.rating -ne $null) -and ([int]($c.rating) -gt 0)
    $hasRecord = ($c.record_id -ne $null) -and ([int]($c.record_id) -ne 0)
    if ($OnlyReviews -and -not ($hasRating -or $hasRecord)) { continue }

    # map fields required by Tilda: id, rating, text, user_name (and parsed first/last), master_id, record_id, date
    $userName = $null
    if ($c.user_name) { $userName = $c.user_name } elseif ($c.user_name_raw) { $userName = $c.user_name_raw } elseif ($c.user) { $userName = $c.user.name } else { $userName = $c.user_name }
    $first = $null; $last = $null
    if ($userName) {
      $parts = $userName -split '\s+' | Where-Object { $_ -ne '' }
      if ($parts.Count -ge 2) { $first = $parts[0]; $last = ($parts[1..($parts.Count-1)] -join ' ') } else { $first = $userName }
    }

    $evt = [PSCustomObject]@{
      event = 'comment.created'
      data = [PSCustomObject]@{
        id = ($c.id -as [string])
        salon_id = ($c.salon_id -as [string])
        master_id = ($c.master_id -as [string])
        type = $c.type
        record_id = ($c.record_id -as [string])
        rating = (if ($c.rating -ne $null) { [int]$c.rating } else { $null })
        text = $c.text
        date = $c.date
        user_id = ($c.user_id -as [string])
        user_name = $userName
        user_first = $first
        user_last = $last
        user_avatar = $c.user_avatar
      }
    }

    # Do not include raw object in production payloads; keep it for DryRun inspection only
    if ($DryRun) { $evt.data.raw = $c }

    $allEvents += $evt
  }
}

# Two fetch modes: server-side rating filtering (faster, less noise) or client-side full walk
$rateValues = 5..1
if ($ServerSideRating) {
  Write-Output "ServerSideRating enabled: fetching rated comments by rating=5..1"
  foreach ($rating in $rateValues) {
    $page = 1
    while ($true) {
      $target = "https://api.yclients.com/api/v1/comments/$CompanyId/?page=$page&count=$PageSize&rating=$rating"
      Write-Output "Fetching rating=$rating page $page..."
      $resp = Invoke-YClientsGet -url $target
      if (-not $resp) { break }
      $items = @()
      if ($resp -is [System.Collections.IEnumerable]) { $items = $resp } elseif ($resp.comments) { $items = $resp.comments } else { $items = @($resp) }
      if ($items.Count -eq 0) { break }
      $scannedItems += $items.Count
      Process-And-MapItems -items $items
      Write-Output "Collected $($allEvents.Count) total events so far (scanned $scannedItems items)"
      if ($items.Count -lt $PageSize) { break }
      if ($MaxPages -gt 0 -and $page -ge $MaxPages) { Write-Output "Reached MaxPages=$MaxPages for rating=$rating; stopping."; break }
      $page++
    }
  }
} else {
  $page = 1
  while ($true) {
    $target = "https://api.yclients.com/api/v1/comments/$CompanyId/?page=$page&count=$PageSize"
    Write-Output "Fetching page $page..."
    $resp = Invoke-YClientsGet -url $target
    if (-not $resp) { break }
    $items = @()
    if ($resp -is [System.Collections.IEnumerable]) { $items = $resp } elseif ($resp.comments) { $items = $resp.comments } else { $items = @($resp) }
    if ($items.Count -eq 0) { break }
    $scannedItems += $items.Count
    Process-And-MapItems -items $items
    Write-Output "Collected $($allEvents.Count) total events so far (scanned $scannedItems items)"
    if ($items.Count -lt $PageSize) { break }
    if ($MaxPages -gt 0 -and $page -ge $MaxPages) { Write-Output "Reached MaxPages=$MaxPages; stopping."; break }
    $page++
  }
}

if ($allEvents.Count -eq 0) { Write-Output 'No events found; exiting'; exit 0 }

# filter out existing ids if we fetched them
if ($existingIds.Count -gt 0) {
  $toImport = $allEvents | Where-Object { -not $existingIds.ContainsKey($_.data.id) }
  Write-Output "After filtering existing ids: $($toImport.Count) to import"
} else {
  $toImport = $allEvents
}

# When running as DryRun, show a representative sample of mapped payloads
if ($DryRun) {
  $total = $toImport.Count
  Write-Output "DryRun: total mapped events to import (after filtering): $total"
  if ($total -gt 0) {
    $sample = $toImport | Select-Object -First 10
    Write-Output "DryRun: showing first $($sample.Count) mapped payloads (ConvertTo-Json depth=6):"
    foreach ($s in $sample) { Write-Output ($s | ConvertTo-Json -Depth 6) }
  }
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
  Write-Output "Importing batch $batchIndex of $($batches.Count) — $($batch.Count) items"
  if ($DryRun) {
    Write-Output "DryRun: would POST batch $batchIndex with $($batch.Count) items to /admin/import (skipping actual POST)"
    # show first few payload examples when dry-running
    $examples = $batch | Select-Object -First 3
    Write-Output "DryRun examples (first 3 items):"
    foreach ($e in $examples) { Write-Output ($e | ConvertTo-Json -Depth 6) }
  } elseif ($AdminKey) {
    $resp = Invoke-AdminImport -payload $batch
    if ($resp -and $resp.results) {
      foreach ($r in $resp.results) {
        if ($r.ok -eq $true -and $r.id) { $importedIds += $r.id }
      }
      Write-Output "Batch result: imported $($resp.imported)"
    } else {
      Write-Output "Batch import returned no result or failed"
    }
  } else {
    Write-Output "AdminKey not provided; skipping POST to /admin/import (diagnostic mode)"
  }
}

if ($SyncDeleteMissing -and $AdminKey) {
  Write-Output "SyncDeleteMissing requested — sending full id list to /admin/sync"
  $syncUri = "$IngestUrl/admin/sync"
  $h = @{ 'X-Admin-Key' = $AdminKey; 'Content-Type' = 'application/json' }
  $body = @{ ids = $allEvents | ForEach-Object { $_.data.id } } | ConvertTo-Json -Depth 4
  try {
    $r = Invoke-RestMethod -Uri $syncUri -Method Post -Headers $h -Body $body -ErrorAction Stop
  Write-Output "Sync response: $($r | ConvertTo-Json -Depth 3)"
  } catch {
    Write-Error "Sync POST failed: $($_.Exception.Message)"
  }
}

Write-Output "Done. Imported ids count: $($importedIds.Count)"
