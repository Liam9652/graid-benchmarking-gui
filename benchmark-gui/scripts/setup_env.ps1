# SupremeRAID Benchmarking Environment Setup Script (Windows Host Mode)
# Version: 1.0.0

Write-Host "Starting SupremeRAID Benchmarking Environment Setup (Windows Host Mode)..." -ForegroundColor Green

# --- 1. Python Check ---
$pythonInstalled = Get-Command python -ErrorAction SilentlyContinue
if ($null -eq $pythonInstalled) {
    Write-Host "Error: Python is not detected. Please install Python 3.8+ from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "Make sure to check 'Add Python to PATH' during installation." -ForegroundColor Yellow
    exit 1
}

$pythonVersion = python --version
Write-Host "Detected Python: $pythonVersion" -ForegroundColor Yellow

# --- 2. Install Dependencies ---
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow

# requirements paths
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$srcReq = Join-Path $scriptDir "src\requirements.txt"
$backendReq = Join-Path $scriptDir "..\backend\requirements.txt"

# Install System deps (src/requirements.txt)
if (Test-Path $srcReq) {
    Write-Host "Installing dependencies from $srcReq..."
    pip install -r $srcReq
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: Failed to install some dependencies from src/requirements.txt" -ForegroundColor Red
    }
}

# Install Backend deps (backend/requirements.txt)
if (Test-Path $backendReq) {
    Write-Host "Installing dependencies from $backendReq..."
    pip install -r $backendReq
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Warning: Failed to install backend requirements." -ForegroundColor Red
    }
}

# --- 3. Final Instructions ---
Write-Host "`nEnvironment setup complete!" -ForegroundColor Green
Write-Host "Running in Host Mode." -ForegroundColor Green

Write-Host "`nTo start the Backend:"
Write-Host "  cd ..\backend" -ForegroundColor Yellow
Write-Host "  python app.py" -ForegroundColor Yellow

Write-Host "`nTo start the Frontend (if needed):"
Write-Host "  cd ..\frontend" -ForegroundColor Yellow
Write-Host "  npm install" -ForegroundColor Yellow
Write-Host "  npm start" -ForegroundColor Yellow

Write-Host "`nSee README_HOST_MODE.md for more details."
