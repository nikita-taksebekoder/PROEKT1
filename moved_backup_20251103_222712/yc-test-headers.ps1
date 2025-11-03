# yc-test-headers.ps1
param(
  [Parameter(Mandatory=$true)][string]$CompanyId,
  [Parameter(Mandatory=$true)][string]$PartnerToken,
  [Parameter(Mandatory=$false)][string]$UserToken,
  [string]$PageSize = '1'
)

$accept = 'application/vnd.yclients.v2+json'
$base = "https://api.yclients.com/api/v1/comments/$CompanyId/?page=1&count=$PageSize"

$tests = @()

# helper to add test
function Add-Test($h) { $tests += ,$h }

function Format-Token($s) {
  if (-not $s) { return '' }
  $len = $s.Length
  if ($len -le 8) { return '****' + $s.Substring([Math]::Max(0,$len-4)) }
  return $s.Substring(0,4) + '****' + $s.Substring($len-4)
}

# Basic likely candidates
Add-Test @{ 'Accept' = $accept; 'Authorization' = "Bearer $PartnerToken" }
if ($UserToken) { Add-Test @{ 'Accept'=$accept; 'Authorization' = "Bearer $UserToken" } }
Add-Test @{ 'Accept' = $accept; 'X-Partner-Token' = $PartnerToken }
if ($UserToken) { Add-Test @{ 'Accept' = $accept; 'X-User-Token' = $UserToken } }

# Common combinations
if ($UserToken) { Add-Test @{ 'Accept'=$accept; 'Authorization' = "Bearer $PartnerToken"; 'X-User-Token' = $UserToken } }
if ($UserToken) { Add-Test @{ 'Accept'=$accept; 'X-Partner-Token' = $PartnerToken; 'X-User-Token' = $UserToken } }
Add-Test @{ 'Accept' = $accept; 'Authorization' = "Partner $PartnerToken" }
Add-Test @{ 'Accept' = $accept; 'Authorization' = "Token $PartnerToken" }
if ($UserToken) { Add-Test @{ 'Accept' = $accept; 'Authorization' = "Bearer $PartnerToken, User $UserToken" } }
if ($UserToken) { Add-Test @{ 'Accept' = $accept; 'Authorization' = "User $UserToken" } }

# Additional variants to try (underscores, alternative names, partner as header while user in Authorization etc.)
if ($UserToken) { Add-Test @{ 'Accept'=$accept; 'Authorization' = "Bearer $UserToken"; 'X-Partner-Token' = $PartnerToken } }
if ($UserToken) { Add-Test @{ 'Accept'=$accept; 'Authorization' = "Bearer $PartnerToken"; 'User_Token' = $UserToken } }
if ($UserToken) { Add-Test @{ 'Accept'=$accept; 'X-User_Token' = $UserToken; 'X-Partner_Token' = $PartnerToken } }
Add-Test @{ 'Accept' = $accept; 'Partner-Token' = $PartnerToken }
Add-Test @{ 'Accept' = $accept; 'PartnerToken' = $PartnerToken }
Add-Test @{ 'Accept' = $accept; 'X-Api-Key' = $PartnerToken }
if ($UserToken) { Add-Test @{ 'Accept'=$accept; 'X-Api-Key' = $UserToken } }

# Try partner/user as query params (some APIs accept tokens in query — unlikely but quick to test)
Add-Test @{ 'Accept' = $accept; 'QueryPartner' = "partner=$PartnerToken" }
if ($UserToken) { Add-Test @{ 'Accept' = $accept; 'QueryUser' = "user=$UserToken" } }

# Try company id headers (sometimes required besides URL)
Add-Test @{ 'Accept' = $accept; 'X-Company-Id' = $CompanyId }
Add-Test @{ 'Accept' = $accept; 'Company-Id' = $CompanyId }

# Run tests using HttpClient (avoids exceptions on 4xx/5xx and always reads body)
$idx = 0
$client = New-Object System.Net.Http.HttpClient
foreach ($hdr in $tests) {
  $idx++
  Write-Output "---- Attempt #$idx ----"
  # Build masked headers string for display
  $pairs = @()
  foreach ($k in $hdr.Keys) {
    $v = $hdr[$k]
    if ($k -match 'Query') { $pairs += "[query-test] $v"; continue }
  $pairs += "{0}='{1}'" -f $k, (Format-Token $v)
  }
  Write-Output "Headers: " ($pairs -join ', ')

  # Build request
  $req = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $base)
  foreach ($k in $hdr.Keys) {
    $v = $hdr[$k]
    if ($k -match '^Query') { continue } # skip pseudo-params
    # add header without validation to allow custom names
    $null = $req.Headers.TryAddWithoutValidation($k, $v)
  }

  try {
    $resp = $client.SendAsync($req).Result
    $code = [int]$resp.StatusCode
    $body = $resp.Content.ReadAsStringAsync().Result
  Write-Output "HTTP: $code"
  Write-Output "Body:`n$body`n"
  } catch {
  Write-Output "Request failed with exception: $($_.Exception.Message)"
  }
}

Write-Output "Done. If none returned 200, please paste the full output (masked values ok) so I can pick next steps."