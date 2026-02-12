# GRAID Benchmarking GUI - Host Mode Guide

This guide explains how to run the GRAID Benchmarking GUI in **Host Mode** (also known as Viewer/Client Mode). This mode is designed for machines that do not have the SupremeRAID™ driver or NVIDIA GPU installed (e.g., MacBooks, Windows laptops, or management servers).

In Host Mode, you can:
- View benchmark results.
- Connect to remote DUTs (Device Under Test) via SSH to run benchmarks.
- Manage configuration files.

## Prerequisites

### 1. Python 3.8+
Ensure you have Python installed.
- **Mac**: `brew install python`
- **Windows**: Download from [python.org](https://www.python.org/)
- **Linux**: `sudo apt install python3 python3-pip` (Ubuntu/Debian)

### 2. Node.js (Optional but Recommended)
Required if you want to run the Frontend development server.
- **Mac**: `brew install node`
- **Windows**: Download from [nodejs.org](https://nodejs.org/)
- **Linux**: Use `nvm` or system package manager.

## Installation & Setup

We provide a script to automatically set up the environment based on your system status.

```bash
# Linux / Mac (Bash)
./scripts/setup_env.sh

# Windows (PowerShell)
.\scripts\setup_env.ps1
```

The script will detect that you don't have the SupremeRAID™ driver and automatically configure **Host Mode**. It will:
1. Install Python dependencies (Flask, pandas, paramiko, etc.).
2. Skip Docker and Driver installation.

## Running the Application Manually

If you prefer to run it manually or are on Windows (without WSL), follow these steps:

### 1. Start the Backend
The backend serves the API and can also serve the static frontend files if built.

```bash
cd backend
pip3 install -r requirements.txt
python3 app.py
```
*The backend will start on port 50071.*

### 2. Start the Frontend
You have two options:

#### Option A: Run source code (Development Mode)
This requires Node.js.
```bash
cd frontend
npm install
npm start
```
*The frontend will open at http://localhost:3000.*

#### Option B: Serve built files via Backend
If the `frontend/build` folder exists (pre-built), the Python backend will serve it at `http://localhost:50071`.

## Remote Benchmarking
To benchmark a remote server (DUT) from this Host Mode instance:
1. Open the UI.
2. Go to **Config** > **DUT Settings**.
3. Enable **Remote Mode**.
4. Enter the **IP**, **User**, and **Password** of the machine with the SupremeRAID™ card.
5. Save and Start Benchmark.
