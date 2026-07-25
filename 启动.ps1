# ==============================================================================
# One-click launcher: Data Analysis Agent Platform
# Usage:
#   .\启动.ps1                # start backend + frontend and open browser
#   .\启动.ps1 -NoBrowser     # do not auto-open browser
#   .\启动.ps1 -Stop          # stop all processes started by this script
#   .\启动.ps1 -Check         # dependency/config check only, no start
# ==============================================================================

[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$Check,
    [switch]$NoBrowser,
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 8501
)

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
$PidFile = Join-Path $ProjectRoot ".reasonix\run\daa_pids.json"

# ---------- helpers ----------

function Write-Step($msg) { Write-Host "[*] $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Write-Err($msg)  { Write-Host "[X] $msg" -ForegroundColor Red }

function Test-PortFree($port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return -not $conn
}

function Find-FreePort($start, $maxTry = 10) {
    for ($i = 0; $i -lt $maxTry; $i++) {
        $p = $start + $i
        if (Test-PortFree $p) { return $p }
    }
    return -1
}

function Get-StoredPids {
    if (-not (Test-Path $PidFile)) { return $null }
    try {
        return Get-Content $PidFile -Raw | ConvertFrom-Json
    } catch { return $null }
}

function Save-Pids($backendPid, $frontendPid) {
    $dir = Split-Path $PidFile -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $obj = [PSCustomObject]@{
        backend  = $backendPid
        frontend = $frontendPid
        started  = (Get-Date).ToString("o")
    }
    $obj | ConvertTo-Json | Set-Content $PidFile -Encoding UTF8
}

function Stop-Pid($processId) {
    if (-not $processId) { return }
    try {
        $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($proc) {
            Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
            Write-Ok "Stopped PID $processId ($($proc.ProcessName))"
        }
    } catch {}
}

# ---------- checks ----------

function Invoke-Checks {
    Write-Step "Checking project root"
    if (-not (Test-Path (Join-Path $ProjectRoot "api\main.py"))) {
        Write-Err "api\main.py not found; run from project root"
        exit 1
    }
    Write-Ok "Project root: $ProjectRoot"

    Write-Step "Checking Python"
    try {
        $pyVer = python --version 2>&1
        Write-Ok "Python: $pyVer"
    } catch {
        Write-Err "python not found"
        exit 1
    }

    Write-Step "Checking Python deps (fastapi/uvicorn/pandas/requests/dotenv/openpyxl)"
    $depCheck = python -c "import fastapi, uvicorn, pandas, requests, dotenv, openpyxl; print('OK')" 2>&1
    if ($depCheck -ne "OK") {
        Write-Warn "Missing deps, attempting: pip install -r requirements.txt"
        pip install -r requirements.txt
        $depCheck = python -c "import fastapi, uvicorn, pandas, requests, dotenv, openpyxl; print('OK')" 2>&1
    }
    if ($depCheck -ne "OK") {
        Write-Err "Deps still missing. Run manually: pip install -r requirements.txt"
        exit 1
    }
    Write-Ok "Deps OK"

    Write-Step "Checking .env LLM_API_KEY"
    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path $envFile)) {
        Write-Warn ".env not found; LLM intent will use keyword fallback (still runnable)"
    } else {
        $envContent = Get-Content $envFile -Raw
        if ($envContent -match 'LLM_API_KEY\s*=\s*(your_llm_api_key|sk-\s*$|\s*$)') {
            Write-Warn "LLM_API_KEY is placeholder; LLM intent will use keyword fallback (still runnable)"
        } elseif ($envContent -match 'LLM_API_KEY\s*=\s*\S+') {
            Write-Ok "LLM_API_KEY configured; LLM intent will call LLM"
        } else {
            Write-Warn "LLM_API_KEY not found; will use keyword fallback"
        }
    }
}

# ---------- stop ----------

function Invoke-Stop {
    Write-Step "Stopping processes"
    $pids = Get-StoredPids
    if (-not $pids) {
        Write-Warn "No PID record file found"
        return
    }
    Stop-Pid $pids.frontend
    Stop-Pid $pids.backend
    if (Test-Path $PidFile) { Remove-Item $PidFile -Force }
    Write-Ok "All stopped"
}

# ---------- start ----------

function Start-Backend($port) {
    Write-Step "Starting backend (FastAPI) @ 127.0.0.1:$port"
    # Launcher script written to project root to ensure cwd is correct
    $launcher = @'
import os, sys
sys.path.insert(0, os.getcwd())
import uvicorn
from api.main import app
uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
'@
    $launcherPath = Join-Path $ProjectRoot ".reasonix\run\daa_backend_launcher.py"
    $dir = Split-Path $launcherPath -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($launcherPath, $launcher, (New-Object System.Text.UTF8Encoding $false))
    $proc = Start-Process -PassThru -WindowStyle Hidden `
        -FilePath "python" `
        -ArgumentList "`"$launcherPath`"", "$port" `
        -WorkingDirectory $ProjectRoot
    $cur = Get-StoredPids
    Save-Pids -backendPid $proc.Id -frontendPid $cur.frontend
    Start-Sleep -Seconds 4
    $alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if (-not $alive) {
        Write-Err "Backend failed to start. Run manually: python api\main.py"
        exit 1
    }
    Write-Ok "Backend PID $($proc.Id)"
}

function Start-Frontend($port) {
    Write-Step "Starting frontend (HTML) @ 127.0.0.1:$port"
    # Build the Chinese module name at runtime to avoid any encoding pitfall across
    # PowerShell here-string / Set-Content / file IO layers.
    $launcher = @'
import os, sys
sys.path.insert(0, os.getcwd())
import uvicorn
# Module name is 前端_html.app:app, assembled via chr() to avoid encoding issues
_name = chr(0x524d) + chr(0x7aef) + "_html.app:app"
uvicorn.run(_name, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
'@
    $launcherPath = Join-Path $ProjectRoot ".reasonix\run\daa_frontend_launcher.py"
    $dir = Split-Path $launcherPath -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    [System.IO.File]::WriteAllText($launcherPath, $launcher, (New-Object System.Text.UTF8Encoding $false))
    $proc = Start-Process -PassThru -WindowStyle Hidden `
        -FilePath "python" `
        -ArgumentList "`"$launcherPath`"", "$port" `
        -WorkingDirectory $ProjectRoot
    $cur = Get-StoredPids
    Save-Pids -backendPid $cur.backend -frontendPid $proc.Id
    Start-Sleep -Seconds 4
    $alive = Get-Process -Id $proc.Id -ErrorAction SilentlyContinue
    if (-not $alive) {
        Write-Err "Frontend failed to start. Run manually: uvicorn 前端_html.app:app --port $port"
        exit 1
    }
    Write-Ok "Frontend PID $($proc.Id)"
}

# ---------- main ----------

if ($Stop) {
    Invoke-Stop
    exit 0
}

$script:InCheckMode = $Check.IsPresent
Invoke-Checks
if ($Check) { exit 0 }

$bp = Find-FreePort $BackendPort
$fp = Find-FreePort $FrontendPort
if ($bp -lt 0) { Write-Err "Ports $BackendPort+ all in use"; exit 1 }
if ($fp -lt 0) { Write-Err "Ports $FrontendPort+ all in use"; exit 1 }
if ($bp -ne $BackendPort) { Write-Warn "Backend port $BackendPort in use, using $bp" }
if ($fp -ne $FrontendPort) { Write-Warn "Frontend port $FrontendPort in use, using $fp" }

Start-Backend -port $bp
Start-Frontend -port $fp
Start-Sleep -Seconds 2

Write-Step "Health check backend /health"
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$bp/health" -TimeoutSec 5 -ErrorAction Stop
    Write-Ok "Backend health: $($resp.status)"
} catch {
    Write-Warn "Backend /health not ready yet (maybe still initializing)"
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Ok "Data Analysis Agent Platform started"
Write-Host "  Backend API:  http://127.0.0.1:$bp"       -ForegroundColor White
Write-Host "  API Docs:     http://127.0.0.1:$bp/docs"   -ForegroundColor White
Write-Host "  Frontend:     http://127.0.0.1:$fp"            -ForegroundColor White
Write-Host "================================================" -ForegroundColor Green
Write-Host "Stop with: .\启动.ps1 -Stop"                    -ForegroundColor DarkGray
Write-Host ""

if (-not $NoBrowser) {
    Write-Step "Opening browser"
    Start-Process "http://127.0.0.1:$fp"
    Write-Ok "Opened"
}

Write-Host "Services run in background. You can close this terminal. Stop with: .\启动.ps1 -Stop" -ForegroundColor DarkGray
