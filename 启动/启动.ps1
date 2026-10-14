# ============================================================================
# 【文件定位】本地一键启动脚本（PowerShell）：拉起后端 uvicorn + 前端 vite dev。
#            正式演示请用同目录的「一键启动-正式.bat」。
# 【做了什么】
#   1) 依赖自检：python -c 试 import fastapi/uvicorn/pandas/requests，缺了才 pip install；
#      frontend/node_modules 不存在才 npm install（有则跳过，绝不主动更新）；
#   2) 端口自愈：从 8000/5173 起向后试 20 个端口，取第一个能连上的（被占就自动换）；
#   3) 后端：Start-Process 后台隐藏窗口跑 `uvicorn api.main:app --workers 1`；
#   4) 前端：新开 cmd 窗口跑 vite dev；最后把两个 PID 写进 .reasonix/run/pids.json，
#      并用 /health 探一次活；-Stop 参数按该文件里的 PID 关掉两个进程。
# 【为什么这么做】
#   - **必须 `--workers 1`**（阶段 54 起）：SQLite 写锁是进程内 threading.Lock，
#     多 worker 会撞 `database is locked`。阶段六十一更把它变成后端启动硬闸，
#     传 `--workers > 1` 会被 `api/main.py` 的启动自检直接拒绝（连启动都不让）。
#     切 MySQL（`DB_BACKEND=mysql`）后才可按需放开。
#   - **chromadb 也是单进程本地持久化**：多进程同时打开同一目录会互相踩，
#     这是阶段六十一加那道闸的第二个理由。
#   - 依赖只在缺失时安装、不主动升级，避免"重启一次换个版本"这种不可复现事故。
# 【关键约定与坑】
#   - 本脚本只负责启动；配置一律读项目根 `.env`（改完必须重启后端才生效，
#     EnvConfig 属性在 import 时求值一次）。
#   - 端口被占不是错误而是常态（同时开多个项目/上次没停干净），所以是自愈而非报错；
#     但前端窗口是新开的终端，关掉主窗口不会关它，停服务请用 `.\启动.ps1 -Stop`。
#   - `.reasonix/run/pids.json` 是唯一的状态记录；手工杀进程后该文件会留下陈旧 PID，
#     下次 -Stop 会静默忽略（Stop-Process -ErrorAction SilentlyContinue），不会报错。
# ============================================================================
param([switch]$Stop,[switch]$NoBrowser,[int]$BackendPort=8000,[int]$FrontendPort=5173)
$r=Join-Path $PSScriptRoot ".."
$pf=Join-Path $r ".reasonix\run\pids.json"
function s($m){Write-Host "`n[>>] $m" -ForegroundColor Cyan}
function o($m){Write-Host "[OK] $m" -ForegroundColor Green}
function w($m){Write-Host "[!] $m" -ForegroundColor Yellow}
function e($m){Write-Host "[X] $m" -ForegroundColor Red;exit 1}
# 端口检测：找到第一个空闲端口
function Get-FreePort([int]$Start) {
    for($p=$Start;$p -le $Start+20;$p++){
        try{$t=New-Object System.Net.Sockets.TcpClient;$t.Connect("127.0.0.1",$p);$t.Close()}catch{return $p}
    }
    return $Start
}
if($Stop){
    if(Test-Path $pf){$p=Get-Content $pf|ConvertFrom-Json
        if($p.backend){Stop-Process -Id $p.backend -Force -ErrorAction SilentlyContinue}
        if($p.frontend){Stop-Process -Id $p.frontend -Force -ErrorAction SilentlyContinue}
        Remove-Item $pf -Force;o "Stopped"}else{w "No running processes"};exit 0}
# 检测端口是否被占用
$BackendPort=Get-FreePort $BackendPort
$FrontendPort=Get-FreePort $FrontendPort
s "Checking deps"
python -c "import fastapi,uvicorn,pandas,requests; print('ok')" 2>$null
if($LASTEXITCODE -ne 0){w "Installing Python deps...";pip install -r (Join-Path $r "requirements.txt") 2>&1|Out-Null
    python -c "import fastapi,uvicorn,pandas,requests; print('ok')" 2>$null
    if($LASTEXITCODE -ne 0){e "pip install failed"}}
$fd=Join-Path $r "frontend"
if(-not (Test-Path (Join-Path $fd "node_modules"))){w "Installing Node deps...";Push-Location $fd;npm install 2>&1|Out-Null;Pop-Location}
o "Deps ready"
if($BackendPort -ne 8000 -or $FrontendPort -ne 5173){w "Ports in use, using Backend=$BackendPort Frontend=$FrontendPort"}
s "Starting backend"
# 【阶段54】SQLite 写锁是进程内 threading.Lock：多 worker 会撞 database is locked，
# 故 SQLite 模式必须 --workers 1。切换 MySQL（DB_BACKEND=mysql）后可按需放开 workers。
# 【阶段六十一】--workers 1 现在还有第二个理由：chromadb 本地持久化不支持多进程同开一个目录；
# 而且后端启动自检会把 --workers > 1 当成不安全配置**直接拒绝启动**，
# 报错文案指向向量记忆，容易让人以为要先关记忆功能——实际正解就是保持单 worker。
$bp=Start-Process -PassThru -WindowStyle Hidden -FilePath "python" -ArgumentList "-m","uvicorn","api.main:app","--host","127.0.0.1","--port","$BackendPort","--workers","1","--log-level","warning" -WorkingDirectory $r
Start-Sleep -Seconds 3
if(-not (Get-Process -Id $bp.Id -ErrorAction SilentlyContinue)){e "Backend failed"}
o "Backend: http://127.0.0.1:$BackendPort (PID $($bp.Id))"
s "Starting frontend (new window)"
$fc=Join-Path $fd "node_modules\.bin\vite.cmd"
if(-not (Test-Path $fc)){w "vite.cmd not found, trying npm run dev"}
Start-Process -WindowStyle Normal -FilePath "cmd.exe" -ArgumentList "/c","npm","run","dev","--","--port","$FrontendPort","--host" -WorkingDirectory $fd
Start-Sleep -Seconds 5
$nodePid=$null
try{$nodePid=(Get-Process -Name node -ErrorAction SilentlyContinue|Where-Object{$_.MainWindowTitle -like "*vite*" -or $_.CommandLine -like "*vite*"}|Select-Object -First 1).Id}catch{}
if(-not $nodePid){try{$nodePid=(Get-Process -Name node -ErrorAction SilentlyContinue|Select-Object -First 1).Id}catch{}}
if($nodePid){o "Frontend: http://127.0.0.1:$FrontendPort (PID $nodePid)"}else{w "Frontend window opened, check taskbar"}
$dir=Split-Path $pf -Parent;if(-not (Test-Path $dir)){New-Item -ItemType Directory -Path $dir -Force|Out-Null}
@{backend=$bp.Id;frontend=$nodePid}|ConvertTo-Json|Set-Content $pf -Encoding UTF8
Start-Sleep -Seconds 2
try{$resp=Invoke-RestMethod "http://127.0.0.1:$BackendPort/health" -TimeoutSec 5;o "Health: $($resp.status)"}catch{w "Health not ready"}
Write-Host "`n====================================" -ForegroundColor Green
o "Data Analysis Agent Platform started"
Write-Host "  UI:   http://127.0.0.1:$FrontendPort" -ForegroundColor White
Write-Host "  API:  http://127.0.0.1:$BackendPort/docs" -ForegroundColor White
Write-Host "  Stop: .\启动.ps1 -Stop" -ForegroundColor White
Write-Host "====================================`n" -ForegroundColor Green
if(-not $NoBrowser){Start-Process "http://127.0.0.1:$FrontendPort"}