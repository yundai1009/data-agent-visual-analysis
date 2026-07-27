# ==============================================================================
# 一键启动脚本
# 用法:
#   .\启动.ps1                 # 启动后端+前端+打开浏览器
#   .\启动.ps1 -NoBrowser     # 不打开浏览器
#   .\启动.ps1 -Stop          # 停止所有进程
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$NoBrowser,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173
)

$ProjectRoot = $PSScriptRoot
$PidFile = Join-Path $ProjectRoot ".reasonixrunpids.json"

function Step($m)  { Write-Host "`n[>>] $m" -ForegroundColor Cyan }
function Ok($m)    { Write-Host "[OK] $m" -ForegroundColor Green }
function Warn($m)  { Write-Host "[!] $m" -ForegroundColor Yellow }
function Err($m)   { Write-Host "[X] $m" -ForegroundColor Red; exit 1 }

if ($Stop) {
    if (Test-Path $PidFile) {
        $pids = Get-Content $PidFile | ConvertFrom-Json
        foreach ($p in @($pids.backend, $pids.frontend)) {
            if ($p) { Stop-Process -Id $p -Force; Ok "Stopped PID $p" }
        }
        Remove-Item $PidFile -Force
    } else { Warn "No running processes found" }
    exit 0
}

# 1. Backend deps
Step "Checking backend dependencies"
$depOk = python -c "import fastapi, uvicorn, pandas, requests; print('ok')" 2>&1
if ($depOk -ne "ok") {
    Warn "Missing deps, installing..."
    pip install -r (Join-Path $ProjectRoot "requirements.txt") 2>&1 | Out-Null
    $depOk = python -c "import fastapi, uvicorn, pandas, requests; print('ok')" 2>&1
    if ($depOk -ne "ok") { Err "Install failed, try: pip install -r requirements.txt" }
}
Ok "Backend deps ready"

# 2. Frontend deps
Step "Checking frontend dependencies"
$frontendDir = Join-Path $ProjectRoot "frontend"
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Warn "node_modules not found, installing..."
    Push-Location $frontendDir
    npm install 2>&1 | Out-Null
    Pop-Location
}
Ok "Frontend deps ready"

# 3. Start backend
Step "Starting backend API"
$beProc = Start-Process -PassThru -WindowStyle Hidden -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--log-level", "warning" `
    -WorkingDirectory $ProjectRoot
Start-Sleep -Seconds 3
if (-not (Get-Process -Id $beProc.Id -ErrorAction SilentlyContinue)) {
    Err "Backend failed to start"
}
Ok "Backend running on http://127.0.0.1:$BackendPort"

# 4. Start frontend
Step "Starting frontend"
$feProc = Start-Process -PassThru -WindowStyle Hidden -FilePath "npx" `
    -ArgumentList "vite", "--port", "$FrontendPort", "--host" `
    -WorkingDirectory $frontendDir
Start-Sleep -Seconds 4
Ok "Frontend running on http://127.0.0.1:$FrontendPort"

# 5. Save PIDs
$dir = Split-Path $PidFile -Parent
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
@{ backend = $beProc.Id; frontend = $feProc.Id } | ConvertTo-Json | Set-Content $PidFile -Encoding UTF8

# 6. Health check
Start-Sleep -Seconds 2
try {
    $resp = Invoke-RestMethod "http://127.0.0.1:$BackendPort/health" -TimeoutSec 5
    Ok "Health check: $($resp.status)"
} catch { Warn "Health check not ready yet" }

# 7. Done
Write-Host "`n====================================" -ForegroundColor Green
Ok "Data Analysis Agent Platform started"
Write-Host "  API:    http://127.0.0.1:$BackendPort" -ForegroundColor White
Write-Host "  Docs:   http://127.0.0.1:$BackendPort/docs" -ForegroundColor White
Write-Host "  UI:     http://127.0.0.1:$FrontendPort" -ForegroundColor White
Write-Host "  Stop:   .\启动.ps1 -Stop" -ForegroundColor White
Write-Host "====================================`n" -ForegroundColor Green

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort"
}
