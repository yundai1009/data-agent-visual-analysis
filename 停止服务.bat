@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Stopping Data Analysis Agent Platform service...

powershell -NoProfile -Command ^
  "$pidFile = Join-Path (Get-Location) '.reasonix\run\silent_pid.json';" ^
  "$killed = $false;" ^
  "if (Test-Path $pidFile) { try { $d = Get-Content $pidFile -Raw | ConvertFrom-Json; if ($d.backend_pid) { Stop-Process -Id $d.backend_pid -Force -ErrorAction SilentlyContinue; $killed = $true } } catch {} };" ^
  "Get-CimInstance Win32_Process -Filter \"Name like '%%python%%'\" | Where-Object { $_.CommandLine -match 'uvicorn' -and $_.CommandLine -match 'api\.main' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; $killed = $true };" ^
  "if ($killed) { Write-Host 'Services stopped.' } else { Write-Host 'No running service found.' }"

echo Done.