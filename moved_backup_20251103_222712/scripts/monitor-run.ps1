param(
    [Parameter(Mandatory=$true)]
    [long]$RunId
)

Write-Output "Starting monitor for run $RunId (poll every 300s)"
while ($true) {
    $ts = Get-Date -Format o
    try {
        $log = gh run view $RunId --log 2>$null
    } catch {
        $log = "(gh command failed)"
    }

    if ($log -match 'Complete job' -or $log -match 'Completed job' -or $log -match 'Conclusion:') {
        Write-Output "$ts - STATUS: finished"
        Write-Output '--- Final log start ---'
        Write-Output $log
        Write-Output '--- Final log end ---'
        break
    } else {
        $patterns = @(
            'Running controlled backfill',
            'Warning: AdminKey',
            'Fetching page',
            'Collected',
            'No events found',
            '/admin/import',
            "The term '-IngestUrl'",
            'error',
            'Exception',
            'POST'
        )
        $lines = @()
        foreach ($p in $patterns) {
            $m = $log | Select-String -Pattern $p -SimpleMatch -List
            if ($m) { $lines += $m.Line }
        }
        if ($lines.Count -eq 0) {
            Write-Output "$ts - STATUS: in_progress (no key lines found)"
        } else {
            Write-Output "$ts - STATUS: in_progress - key lines:"
            $lines | ForEach-Object { Write-Output " - $_" }
        }
    }

    Start-Sleep -Seconds 300
}
