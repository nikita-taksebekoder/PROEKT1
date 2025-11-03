$wk = 'https://yclients-proxy-to-tilda.rookman13.workers.dev'
$adminKey = '464FRq3MMbudGBKrjTFDT8YMIolhl5zlJ70EbDfSqYylQ5wYuQ83pcA5OQiAvaIy'

Write-Host "Fetching keys from $wk/admin/list-ids ..."
$keysResp = Invoke-RestMethod -Method Get -Uri "$wk/admin/list-ids" -Headers @{ 'X-Admin-Key' = $adminKey }
$keys = $keysResp.keys
Write-Host "Total keys: $($keys.Count)"

$results = @()
foreach ($k in $keys) {
    try {
        $ev = Invoke-RestMethod -Method Get -Uri "$wk/event/$k" -ErrorAction Stop
        if ($ev.compact -and $ev.compact.text) {
            $t = $ev.compact.text
        } elseif ($ev.body -and $ev.body.data -and $ev.body.data.text) {
            $t = $ev.body.data.text
        } else {
            $t = ''
        }
        $t = ($t -as [string]).Trim()
        if ($t -eq '') { $t = '__EMPTY__' }
        $results += [pscustomobject]@{ id = $k; text = $t }
    } catch {
        $results += [pscustomobject]@{ id = $k; text = '__ERROR__' }
    }
}

# Group by text and select duplicates
$groups = $results | Group-Object -Property text | Where-Object { $_.Count -gt 1 } | ForEach-Object {
    [pscustomobject]@{
        text = $_.Name
        count = $_.Count
        ids = ($_.Group | ForEach-Object { $_.id }) -join ','
    }
}

if ($groups.Count -gt 0) {
    Write-Host "Duplicate groups found:`n"
    $groups | ConvertTo-Json -Depth 6
} else {
    Write-Host "No duplicate texts found"
}
