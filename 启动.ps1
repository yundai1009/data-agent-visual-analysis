# ==============================================================================
# 一键启动脚本
# 用法:
#   .\启动.ps1                 # 启动后端 + 前端 + 打开浏览器
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
$PidFile = Join-Path $ProjectRoot ".reasonix\run\pids.json"

function Step($msg)  { Write-Host "`n[>>] $msg" -ForegroundColor Cyan }
function Ok($msg)    { Write-Host "[OK] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "[!] $msg" -ForegroundColor Yellow }
function Err($msg)   { Write-Host "[X] $msg" -ForegroundColor Red; exit 1 }

# ─── 停止 ───
if ($Stop) {
    if (Test-Path $PidFile) {
        $pids = Get-Content $PidFile | ConvertFrom-Json
        foreach ($p in @($pids.backend, $pids.frontend)) {
            if ($p) { Stop-Process -Id $p -Force -ErrorAction SilentlyContinue; Ok "已停止 PID $p" }
        }
        Remove-Item $PidFile -Force
    } else {
        Warn "没有运行中的进程记录"
    }
    exit 0
}

# ─── 1. 后端依赖 ───
Step "检查后端依赖"
$depOk = python -c "import fastapi, uvicorn, pandas, requests; print('ok')" 2>&1
if ($depOk -ne "ok") {
    Warn "缺少依赖，正在安装..."
    pip install -r (Join-Path $ProjectRoot "requirements.txt") 2>&1 | Out-Null
    $depOk = python -c "import fastapi, uvicorn, pandas, requests; print('ok')" 2>&1
    if ($depOk -ne "ok") { Err "依赖安装失败，请手动运行: pip install -r requirements.txt" }
}
Ok "后端依赖就绪"

# ─── 2. 前端依赖 ───
Step "检查前端依赖"
$frontendDir = Join-Path $ProjectRoot "frontend"
if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Warn "node_modules 不存在，正在安装..."
    Push-Location $frontendDir
    npm install 2>&1 | Out-Null
    Pop-Location
}
Ok "前端依赖就绪"

# ─── 3. .env 检查 ───
Step "检查 LLM 配置"
$envFile = Join-Path $ProjectRoot ".env"
if (-not (Test-Path $envFile)) {
    Warn ".env 不存在，LLM 功能不可用，将使用关键词匹配兜底"
} else {
    $key = Select-String "LLM_API_KEY\s*=\s*(\S+)" $envFile
    if ($key -and $key.Matches.Groups[1].Value -notmatch '^(your_llm_api_key|sk-?$)$') {
        Ok "LLM_API_KEY 已配置"
    } else {
        Warn "LLM_API_KEY 未配置或为占位符，将使用关键词匹配兜底"
    }
}

# ─── 4. 启动后端 ───
Step "启动后端 (FastAPI @ 127.0.0.1:$BackendPort)"
$beProc = Start-Process -PassThru -WindowStyle Hidden -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "$BackendPort", "--log-level", "warning" `
    -WorkingDirectory $ProjectRoot
Start-Sleep -Seconds 3
if (-not (Get-Process -Id $beProc.Id -ErrorAction SilentlyContinue)) {
    Err "后端启动失败，请手动运行: python -m uvicorn api.main:app --reload --port $BackendPort"
}
Ok "后端已启动 (PID: $($beProc.Id))"

# ─── 5. 启动前端 ───
Step "启动前端 (Vite @ 127.0.0.1:$FrontendPort)"
$feProc = Start-Process -PassThru -WindowStyle Hidden -FilePath "npx" `
    -ArgumentList "vite", "--port", "$FrontendPort", "--host" `
    -WorkingDirectory $frontendDir
Start-Sleep -Seconds 4
if (-not (Get-Process -Id $feProc.Id -ErrorAction SilentlyContinue)) {
    Warn "前端启动失败，请手动运行: cd frontend && npm run dev"
}
Ok "前端已启动 (PID: $($feProc.Id))"

# ─── 6. 保存 PID ───
$dir = Split-Path $PidFile -Parent; if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
@{ backend = $beProc.Id; frontend = $feProc.Id } | ConvertTo-Json | Set-Content $PidFile -Encoding UTF8

# ─── 7. 健康检查 ───
Start-Sleep -Seconds 2
try { $resp = Invoke-RestMethod "http://127.0.0.1:$BackendPort/health" -TimeoutSec 5; Ok "后端健康: $($resp.status)" } catch { Warn "后端健康检查暂未通过" }

# ─── 8. 完成 ───
Write-Host "`n============================================" -ForegroundColor Green
Ok "数据分析 Agent 平台已启动"
Write-Host "  后端接口: http://127.0.0.1:$BackendPort" -ForegroundColor White
Write-Host "  API 文档: http://127.0.0.1:$BackendPort/docs" -ForegroundColor White
Write-Host "  前端页面: http://127.0.0.1:$FrontendPort" -ForegroundColor White
Write-Host "============================================" -ForegroundColor Green
Write-Host "停止: .\启动.ps1 -Stop`n" -ForegroundColor DarkGray

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$FrontendPort"
}
