# SupremeRAID Benchmarking GUI

A web-based GUI for benchmarking SupremeRAID performance, featuring real-time monitoring and result comparison.

## Features

-   **Configuration Management**: Easily configure NVMe devices, RAID types, and test parameters.
-   **One-Click Benchmarking**: Start/Stop benchmarks directly from the web interface.
-   **Real-Time Monitoring**: Visualize IOPS, Bandwidth, and Latency in real-time during tests (powered by `giostat`).
-   **Result Management**: View and compare benchmark results (Baseline vs Graid) with interactive charts.

## Prerequisites

-   Linux OS (tested on Ubuntu/CentOS)
-   Docker and Docker Compose
-   SupremeRAID driver and tools installed (`graidctl`)
-   `giostat` (usually part of sysstat or graid tools)
-   `nvme-cli`, `fio`, `jq`

## Installation & Setup

1.  **Clone the repository**:
    ```bash
    git clone <repository_url>
    cd graid-benchmarking-gui/graid-gui
    ```

2.  **Build and Run with Docker Compose**:
    ```bash
    docker-compose up --build -d
    ```

3.  **Access the Web Interface**:
    Open your browser and navigate to `http://<server-ip>:50072` (Frontend).
    The backend runs on port `50071`.

## Usage

### 1. Configuration
-   Go to the **Config management** tab.
-   Enter your NVMe device list (e.g., `nvme0n1, nvme1n1`).
-   Select RAID types and test parameters.
-   Click **Save Configuration**.

### 2. Benchmarking
-   Go to the **Benchmark** tab.
-   Click **Start Benchmark**.
-   Watch the real-time graphs for performance metrics.
-   Click **Stop Benchmark** to abort if needed.

### 3. Results
-   Go to the **Result** tab.
-   View the list of past benchmarks.
-   **Compare Results**: Select a "Baseline" result (e.g., Physical Drive test) and a "Graid" result (e.g., Virtual Drive test) to see side-by-side comparison charts.

## Development

### Backend
The backend is a Flask application located in `backend/`.
-   `app.py`: Main application logic and API endpoints.
-   `scripts/`: Benchmarking scripts (`graid-bench.sh`).

### Frontend
The frontend is a React application located in `frontend/`.
-   `src/App.jsx`: Main component.
-   `src/components/`: Dashboard components (`RealTimeDashboard`, `ComparisonDashboard`).

## Troubleshooting

-   **Real-time data not showing**: Ensure `giostat` is installed and accessible in the system path. Check the backend logs for errors.
-   **Benchmark fails to start**: Check `logs/` for detailed error messages. Ensure you have root privileges (Docker container runs as privileged).

