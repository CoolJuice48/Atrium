# One-click dev runner: backend + frontend (Windows)
# Usage: .\scripts\dev.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$BackendPort = if ($env:BACKEND_PORT) { $env:BACKEND_PORT } else { "8000" }
$FrontendPort = if ($env:FRONTEND_PORT) { $env:FRONTEND_PORT } else { "3000" }
$env:NEXT_PUBLIC_API_BASE = "http://localhost:$BackendPort"

if (-not (Test-Path ".venv")) {
    Write-Host "No .venv found. Run: make setup (or create venv manually)"
    exit 1
}

Write-Host ""
Write-Host "  Backend:  http://localhost:$BackendPort/docs"
Write-Host "  Frontend: http://localhost:$FrontendPort"
Write-Host ""

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
$venvUvicorn = Join-Path $Root ".venv\Scripts\uvicorn.exe"

$backendJob = Start-Job -ScriptBlock {
    param($uvicorn, $port)
    Set-Location (Join-Path $using:Root "pdf_processor")
    & $uvicorn server.app:app --reload --host 0.0.0.0 --port $port
} -ArgumentList $venvUvicorn, $BackendPort

$frontendJob = Start-Job -ScriptBlock {
    param($port)
    Set-Location (Join-Path $using:Root "frontend")
    npm run dev -- -p $port
} -ArgumentList $FrontendPort

try {
    Wait-Job $backendJob, $frontendJob
} finally {
    Stop-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
    Remove-Job $backendJob, $frontendJob -ErrorAction SilentlyContinue
}
