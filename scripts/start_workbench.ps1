param(
    [int]$ApiPort = 8000,
    [int]$UiPort = 8501
)

$ErrorActionPreference = "Stop"
$WorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$LogRoot = Join-Path $WorkspaceRoot "logs"
if (-not (Test-Path -LiteralPath $LogRoot)) {
    New-Item -ItemType Directory -Path $LogRoot | Out-Null
}

function Test-LocalPort {
    param([int]$Port)
    return $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

$Python = (Get-Command python -ErrorAction Stop).Source
$Started = @()

if (-not (Test-LocalPort -Port $ApiPort)) {
    $ApiProcess = Start-Process -FilePath $Python -WorkingDirectory $WorkspaceRoot -WindowStyle Hidden -PassThru `
        -ArgumentList @("-m", "uvicorn", "ecom_ops.api.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
        -RedirectStandardOutput (Join-Path $LogRoot "workbench-api.stdout.log") `
        -RedirectStandardError (Join-Path $LogRoot "workbench-api.stderr.log")
    $Started += @{ service = "api"; pid = $ApiProcess.Id; url = "http://127.0.0.1:$ApiPort" }
}

if (-not (Test-LocalPort -Port $UiPort)) {
    $UiProcess = Start-Process -FilePath $Python -WorkingDirectory $WorkspaceRoot -WindowStyle Hidden -PassThru `
        -ArgumentList @(
            "-m", "streamlit", "run", "src/ecom_ops/ui/streamlit_app.py",
            "--server.address", "127.0.0.1", "--server.port", "$UiPort",
            "--server.headless", "true", "--browser.gatherUsageStats", "false"
        ) `
        -RedirectStandardOutput (Join-Path $LogRoot "workbench-ui.stdout.log") `
        -RedirectStandardError (Join-Path $LogRoot "workbench-ui.stderr.log")
    $Started += @{ service = "ui"; pid = $UiProcess.Id; url = "http://127.0.0.1:$UiPort" }
}

$StatePath = Join-Path $WorkspaceRoot "data/processed/workbench-processes.json"
@{
    started_at = [DateTimeOffset]::Now.ToString("o")
    processes = $Started
    api_url = "http://127.0.0.1:$ApiPort"
    ui_url = "http://127.0.0.1:$UiPort"
} | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $StatePath -Encoding utf8

Write-Output "AI e-commerce workbench"
Write-Output "UI:  http://127.0.0.1:$UiPort"
Write-Output "API: http://127.0.0.1:$ApiPort/docs"
if ($Started.Count -eq 0) {
    Write-Output "Services were already listening on both ports."
}
