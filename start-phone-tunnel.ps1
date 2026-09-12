param([ValidateRange(1024,65535)][int]$Port = 8765, [ValidateRange(1024,65535)][int]$GatewayPort = 8766)
$ErrorActionPreference = 'Stop'
$stationTunnelRoot = $PSScriptRoot
$stationTunnelPython = Join-Path $stationTunnelRoot '.venv\Scripts\python.exe'
$stationNgrok = (Get-Command ngrok -ErrorAction Stop).Source
$stationTunnelLogs = Join-Path $stationTunnelRoot '.local'
New-Item -ItemType Directory -Force -Path $stationTunnelLogs | Out-Null
$stationExistingTunnel = $false
try {
    $stationTunnels = Invoke-RestMethod 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3
    $stationExistingTunnel = @($stationTunnels.tunnels | Where-Object { $_.config.addr -eq "http://127.0.0.1:$GatewayPort" -and $_.public_url -like 'https://*' }).Count -gt 0
} catch { }
$stationNgrokProcess = $null
if (-not $stationExistingTunnel) {
    $stationNgrokProcess = Start-Process -FilePath $stationNgrok -ArgumentList @('http', "http://127.0.0.1:$GatewayPort", '--inspect=false', '--log=stdout', '--log-format=json', '--log-level=warn') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $stationTunnelLogs 'phone-ngrok.log') -RedirectStandardError (Join-Path $stationTunnelLogs 'phone-ngrok-error.log')
}
$env:STATION_PORT = "$Port"
$env:STATION_GATEWAY_PORT = "$GatewayPort"
Set-Location -LiteralPath $stationTunnelRoot
Write-Host "Private phone pairing: http://localhost:$GatewayPort/pair"
Write-Host "Keep the camera and agent at http://localhost:$Port/?view=camera"
Write-Host 'Keep this window running. Stop it with Ctrl+C after the demo.'
try {
    & $stationTunnelPython -m uvicorn station_steward.phone_gateway:app --host 127.0.0.1 --port $GatewayPort --no-proxy-headers --no-access-log
} finally {
    if ($stationNgrokProcess -and -not $stationNgrokProcess.HasExited) { Stop-Process -Id $stationNgrokProcess.Id }
}
