param([int]$Port = 8765, [string]$PhoneBaseUrl = '', [string]$SerialPort = 'COM3')
$ErrorActionPreference = 'Stop'
$stationRoot = $PSScriptRoot
$stationPython = Join-Path $stationRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $stationPython)) { throw 'Set up the Python environment using README.md first.' }
if (-not (Test-Path -LiteralPath (Join-Path $stationRoot 'mobile\dist\client\index.html'))) { throw 'Build the mobile interface using README.md first.' }
$env:STATION_PORT = "$Port"
$env:STATION_SERIAL_PORT = $SerialPort
if ($PhoneBaseUrl) { $env:STATION_PUBLIC_URL = $PhoneBaseUrl }
Set-Location -LiteralPath $stationRoot
Write-Host "Laptop camera: http://localhost:$Port/?view=camera"
Write-Host 'Open that page and scan its connection QR with your Android phone.'
& $stationPython -m uvicorn station_steward.app:app --host 0.0.0.0 --port $Port
