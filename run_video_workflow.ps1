# ========================================================
# Elinity AI Video Broadcast Workflow One-Click Runner
# ========================================================

Write-Host "========================================================" -ForegroundColor Red
Write-Host "     ELINITY NEWS AGENT: BROADCAST VIDEO WORKFLOW" -ForegroundColor White
Write-Host "========================================================" -ForegroundColor Red

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$PythonExe = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Virtual environment python not found at $PythonExe. Using system python..." -ForegroundColor Yellow
    $PythonExe = "python"
}

Write-Host "Running Master Broadcast Workflow (Top 25 + Trending)..." -ForegroundColor Cyan
& $PythonExe "run_broadcast_workflow.py" @args

Write-Host "`nWorkflow execution completed." -ForegroundColor Green
