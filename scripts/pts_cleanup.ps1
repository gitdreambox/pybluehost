$ErrorActionPreference = 'SilentlyContinue'
$patterns = 'pts_harvest', 'pts_run_batch', 'autoptsclient', 'autoptsserver', 'pts-tester'
Get-CimInstance Win32_Process | Where-Object {
    $cl = $_.CommandLine
    if (-not $cl) { return $false }
    foreach ($p in $patterns) { if ($cl -match $p) { return $true } }
    return $false
} | ForEach-Object {
    Write-Host ("kill {0} {1}" -f $_.ProcessId, $_.Name)
    Stop-Process -Id $_.ProcessId -Force
}
Get-Process PTS | ForEach-Object {
    Write-Host ("kill PTS {0}" -f $_.Id)
    Stop-Process -Id $_.Id -Force
}
Start-Sleep -Seconds 3
Write-Host "--- remaining ---"
Get-CimInstance Win32_Process | Where-Object {
    $cl = $_.CommandLine
    if (-not $cl) { return $false }
    foreach ($p in $patterns) { if ($cl -match $p) { return $true } }
    return $false
} | Select-Object ProcessId, Name | Format-Table -Auto
Get-Process PTS | Select-Object Id | Format-Table -Auto
