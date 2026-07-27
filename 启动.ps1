param([switch]$Stop,[switch]$NoBrowser,[int]$BackendPort=8000,[int]$FrontendPort=5173)
$r=$PSScriptRoot
$pf=Join-Path $r ".reasonix\run\pids.json"
function s($m){Write-Host "`n[>>] $m" -ForegroundColor Cyan}
function o($m){Write-Host "[OK] $m" -ForegroundColor Green}
function w($m){Write-Host "[!] $m" -ForegroundColor Yellow}
function e($m){Write-Host "[X] $m" -ForegroundColor Red;exit 1}
if($Stop){
    if(Test-Path $pf){$p=Get-Content $pf|ConvertFrom-Json
        if($p.backend){Stop-Process -Id $p.backend -Force -ErrorAction SilentlyContinue}
        if($p.frontend){Stop-Process -Id $p.frontend -Force -ErrorAction SilentlyContinue}
        Remove-Item $pf -Force;o "Stopped"}else{w "No running processes"};exit 0}
s "Checking deps"
python -c "import fastapi,uvicorn,pandas,requests; print('ok')" 2>$null
if($LASTEXITCODE -ne 0){w "Installing Python deps...";pip install -r (Join-Path $r "requirements.txt") 2>&1|Out-Null
    python -c "import fastapi,uvicorn,pandas,requests; print('ok')" 2>$null
    if($LASTEXITCODE -ne 0){e "pip install failed"}}
$fd=Join-Path $r "frontend"
if(-not (Test-Path (Join-Path $fd "node_modules"))){w "Installing Node deps...";Push-Location $fd;npm install 2>&1|Out-Null;Pop-Location}
o "Deps ready"
s "Starting backend"
$bp=Start-Process -PassThru -WindowStyle Hidden -FilePath "python" -ArgumentList "-m","uvicorn","api.main:app","--host","127.0.0.1","--port","$BackendPort","--log-level","warning" -WorkingDirectory $r
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