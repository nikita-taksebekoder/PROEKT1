param(
    [Parameter(Mandatory=$true)][string]$Port,
    [int]$Baud = 115200
)
# Quick PowerShell trigger for USB 'VC'
try {
    $sp = New-Object System.IO.Ports.SerialPort $Port, $Baud, 'None', 8, 'One'
    $sp.Open()
    Start-Sleep -Milliseconds 100
    $bytes = [System.Text.Encoding]::ASCII.GetBytes('VC')
    $sp.Write($bytes, 0, $bytes.Length)
    $sp.BaseStream.Flush()
    Start-Sleep -Milliseconds 50
    $sp.Close()
    Write-Host "Sent 'VC' to $Port"
} catch {
    Write-Error $_
    exit 1
}
