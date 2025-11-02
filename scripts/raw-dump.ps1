param(
  [Parameter(Mandatory=$false)][string]$CompanyId = $env:YCLIENTS_COMPANY_ID,
  [int]$PageSize = 100,
  [int]$MaxPages = 20,
  [int]$MaxOutput = 50,
  [string]$ExtraQuery = "",
  [switch]$PrintBodyOnError,
  [switch]$VerboseAuth,
  [switch]$InsecureSkipSsl
)

if (-not $CompanyId) { Write-Error 'CompanyId is required (param or env YCLIENTS_COMPANY_ID)'; exit 2 }

# Tokens from env
$PartnerToken = $env:YCLIENTS_PARTNER_TOKEN
$UserToken = $env:YCLIENTS_USER_TOKEN

if (-not $PartnerToken) { Write-Error 'Partner token missing (env YCLIENTS_PARTNER_TOKEN). Aborting.'; exit 2 }

function Send-Get {
  param($url)
  $handler = New-Object System.Net.Http.HttpClientHandler
  if ($InsecureSkipSsl) { $handler.ServerCertificateCustomValidationCallback = { return $true } }
  $client = New-Object System.Net.Http.HttpClient($handler)

  $attempts = @()
  if ($PartnerToken -and $UserToken) {
    $attempts += @{ 'Authorization' = "Bearer $PartnerToken, User $UserToken"; 'label' = 'Bearer Partner+User' }
  }
  if ($PartnerToken) { $attempts += @{ 'Authorization' = "Bearer $PartnerToken" } }
  # ensure labels for attempts
  for ($i=0;$i -lt $attempts.Count;$i++) {
    if (-not $attempts[$i].ContainsKey('label')) { $attempts[$i]['label'] = "attempt-$($i+1)" }
  }

  foreach ($hdr in $attempts) {
    $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $url)
    foreach ($k in $hdr.Keys) {
      if ($k -eq 'label') { continue }
      $null = $req.Headers.TryAddWithoutValidation($k, $hdr[$k])
    }
    if ($VerboseAuth) { Write-Output ("Trying auth header: {0}" -f $hdr['label']) }
    try {
      $resp = $client.SendAsync($req).Result
      $code = [int]$resp.StatusCode
      $body = $resp.Content.ReadAsStringAsync().Result
      if ($code -ge 200 -and $code -lt 300) { 
        try { return ($body | ConvertFrom-Json) } catch { return $body }
      } else {
        if ($PrintBodyOnError) {
          Write-Output ("HTTP $code returned for $url (auth={0}) -- response body:" -f $hdr['label'])
          Write-Output $body
        } else {
          Write-Output "HTTP $code returned for $url"
        }
      }
    } catch {
      Write-Output "Request exception: $($_.Exception.Message)"
    }
  }
  return $null
}

$all = @()
$scanned = 0
for ($page=1; $page -le $MaxPages; $page++) {
  $url = "https://api.yclients.com/api/v1/comments/$CompanyId/?page=$page&count=$PageSize"
  if ($ExtraQuery -ne "") {
    # ensure leading & if user gave key=val
    if ($ExtraQuery.StartsWith('&')) { $url = $url + $ExtraQuery } else { $url = $url + '&' + $ExtraQuery }
  }
  Write-Output "Fetching page $page -> $url"
  $resp = Send-Get -url $url
  if (-not $resp) { Write-Output "No response or empty page at $page; stopping."; break }
  $items = @()
  if ($resp -is [System.Collections.IEnumerable]) { $items = $resp } elseif ($resp.comments) { $items = $resp.comments } else { $items = @($resp) }
  if ($items.Count -eq 0) { Write-Output "Page $page returned 0 items; stopping."; break }
  $scanned += $items.Count
  Write-Output ("Page {0}: items={1} total-scanned={2}" -f $page, $items.Count, $scanned)
  $all += $items
  # small throttle to avoid hammering
  Start-Sleep -Milliseconds 200
}

Write-Output "Fetched total items: $($all.Count) (scanned count: $scanned)"
if ($all.Count -eq 0) { Write-Output 'No items retrieved.'; exit 0 }

$show = $all | Select-Object -First $MaxOutput
Write-Output "Showing first $($show.Count) raw items (ConvertTo-Json depth=10):"
foreach ($it in $show) { Write-Output ($it | ConvertTo-Json -Depth 10) }

Write-Output 'Done.'
