param(
    [Parameter(Mandatory=$true)][string]$Port,
    [ValidateSet('FAN','PUMP')][string]$Target = 'FAN',
    [ValidateRange(3,10)][int]$Hysteresis = 5,
    [Parameter(Mandatory=$true)][string]$CurveCsv,
    [ValidateSet(0,1,2)][int]$SourceMode = 2,  # 0=CPU,1=GPU,2=MAX
    [ValidateSet(0,1)][int]$InterpMode = 1,    # 0=linear,1=spline
    [int]$Baud = 115200
)

# Curve CSV format: each non-empty line "tempC;percent" (e.g., 30;0)
# Will send FC/PC v2: [ 'F'/'P', 'C', ver=2, src, mode, n, hyst, (n * {tC*10:int16, s:u8}) ]

function Read-CurveCsv {
    param([string]$Path)
    if (!(Test-Path $Path)) { throw "File not found: $Path" }
    $pts = @()
    Get-Content -LiteralPath $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -eq '' -or $line.StartsWith('#')) { return }
        $parts = $line -split '[;,\s]+'
        if ($parts.Count -lt 2) { throw "Bad line: '$line'" }
        $t = [float]$parts[0]
        $s = [int]  $parts[1]
        if ($s -lt 0 -or $s -gt 100) { throw "Percent out of range: $s" }
        $pts += [pscustomobject]@{ tC=$t; s=$s }
    }
    if ($pts.Count -lt 2 -or $pts.Count -gt 16) { throw "Curve points must be 2..16 (got $($pts.Count))" }
    # sort by temperature ascending
    $pts | Sort-Object tC
}

try {
    $pts = Read-CurveCsv -Path $CurveCsv
    $n = [byte]$pts.Count
    $ver = 2
    $src = [byte]$SourceMode
    $mode = [byte]$InterpMode
    $hyst = [byte]$Hysteresis

    $ms = New-Object System.IO.MemoryStream
    $bw = New-Object System.IO.BinaryWriter $ms
    $bw.Write([byte]([char]($Target -eq 'FAN' ? 'F' : 'P')))
    $bw.Write([byte]([char]'C'))
    $bw.Write([byte]$ver)
    $bw.Write([byte]$src)
    $bw.Write([byte]$mode)
    $bw.Write([byte]$n)
    $bw.Write([byte]$hyst)
    foreach ($p in $pts) {
        $tx10 = [int16]([math]::Round($p.tC * 10.0))
        $bw.Write([byte]($tx10 -band 0xFF))
        $bw.Write([byte](($tx10 -shr 8) -band 0xFF))
        $bw.Write([byte]$p.s)
    }
    $bw.Flush()
    $payload = $ms.ToArray()

    $sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, 'None', 8, 'One'
    $sp.Open()
    Start-Sleep -Milliseconds 50
    $sp.Write($payload, 0, $payload.Length)
    $sp.BaseStream.Flush()
    Start-Sleep -Milliseconds 100
    $sp.Close()

    Write-Host "Sent $Target curve v2 with hyst=$Hysteresis% and $n points to $Port"
} catch {
    Write-Error $_
    exit 1
}
