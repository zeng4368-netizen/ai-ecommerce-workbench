param(
    [int]$Port = 8765
)

$ErrorActionPreference = 'Stop'
$dashboardRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue

if (-not $pythonCommand) {
    Write-Host 'Python was not found. Install Python 3.11+ and try again.' -ForegroundColor Red
    Read-Host 'Press Enter to exit'
    exit 1
}

$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCommand) {
    Write-Host 'Node.js is required to run the unchanged Skill calculation engines. Install Node.js 20+.' -ForegroundColor Red
    exit 1
}

$existingListener = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existingListener) {
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        if ($health.status -eq 'ok' -and $health.storage -eq 'SQLite') {
            Start-Process "http://127.0.0.1:$Port/"
            Write-Host 'The existing workbench is open in your browser.' -ForegroundColor Green
            exit 0
        }
    } catch { }
    Write-Host "Port $Port is already in use. Try another port:" -ForegroundColor Yellow
    Write-Host ".\启动综合看板.ps1 -Port 8766"
    Read-Host 'Press Enter to exit'
    exit 1
}

& $pythonCommand.Source -c 'import fastapi, uvicorn, multipart, pandas, openpyxl, dotenv'
if ($LASTEXITCODE -ne 0) {
    Write-Host 'Install dependencies first: python -m pip install -r requirements.txt' -ForegroundColor Yellow
    Read-Host 'Press Enter to exit'
    exit 1
}

$server = Start-Process `
    -FilePath $pythonCommand.Source `
    -ArgumentList 'server.py', '--port', $Port `
    -WorkingDirectory $dashboardRoot `
    -WindowStyle Hidden `
    -PassThru

try {
    $ready = $false
    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        Start-Sleep -Milliseconds 150
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        throw 'The local dashboard server did not start.'
    }

    $url = "http://127.0.0.1:$Port/"
    Start-Process $url
    Write-Host "Dashboard opened: $url" -ForegroundColor Green
    Write-Host 'Keep this window open while using the dashboard.'
    Read-Host 'Press Enter to stop the local server'
}
finally {
    if (-not $server.HasExited) {
        Stop-Process -Id $server.Id
    }
}
