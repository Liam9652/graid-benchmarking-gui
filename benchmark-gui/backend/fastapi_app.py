#!/usr/bin/env python3
"""GRAID Benchmark Web GUI — FastAPI backend

Provides the same REST API as app.py with:
  • Auto-generated OpenAPI docs at /docs and /redoc
  • Pydantic request / response validation
  • Socket.IO real-time events (python-socketio ASGI mode)
  • Optional API-key authentication (BENCHMARK_API_KEY env var)

Run with uvicorn:
    uvicorn fastapi_app:combined_app --host 0.0.0.0 --port 50073 --reload
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
import socketio
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Re-use the core business logic from the Flask app (no Flask objects imported)
# ---------------------------------------------------------------------------
from app import (
    BASE_DIR,
    LOGS_DIR,
    RESULTS_DIR,
    BenchmarkManager,
    BenchmarkState,
    ConfigManager,
    RemoteExecutor,
    _collect_gpu_perf,
    _collect_nvme_pcie_info,
    benchmark_manager,
    parse_graidctl_json,
    strip_ansi,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logger = logging.getLogger("fastapi-benchmark")

# ---------------------------------------------------------------------------
# Socket.IO (async ASGI mode)
# ---------------------------------------------------------------------------
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="GRAID Benchmark GUI API",
    description=(
        "REST API for the GRAID Benchmark Web GUI.  "
        "Provides device configuration, benchmark control, result browsing, "
        "and real-time status via Socket.IO.\n\n"
        "Set the `BENCHMARK_API_KEY` environment variable to enable API-key "
        "authentication for mutating endpoints."
    ),
    version="1.0.0",
    contact={"name": "GRAID Technology"},
    license_info={"name": "Proprietary"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Combine FastAPI + Socket.IO into a single ASGI app
combined_app = socketio.ASGIApp(sio, app)

# ---------------------------------------------------------------------------
# API-key authentication
# ---------------------------------------------------------------------------
_API_KEY: str | None = os.environ.get("BENCHMARK_API_KEY")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    """FastAPI dependency — validates X-API-Key header when env var is set."""
    if _API_KEY and key != _API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ConfigPayload(BaseModel):
    """Benchmark configuration (mirrors graid-bench.conf keys)."""
    DUT_IP: Optional[str] = None
    DUT_PASSWORD: Optional[str] = None
    DUT_USER: Optional[str] = "root"
    DUT_PORT: Optional[int] = 22
    REMOTE_MODE: bool = False
    NVME_LIST: List[str] = Field(default_factory=list)
    NVME_INFO: Optional[str] = None
    RAID_TYPE: List[str] = Field(default_factory=list)
    RAID_CTRLR: Optional[str] = None
    VD_NAME: Optional[str] = None
    PD_RUNTIME: int = 60
    VD_RUNTIME: int = 60
    RUN_PD: bool = True
    RUN_PD_ALL: bool = True
    RUN_VD: bool = True
    RUN_MD: bool = False
    QUICK_TEST: bool = False
    FIO_BLOCK_SIZES: List[str] = Field(default_factory=list)
    FIO_MODES: List[str] = Field(default_factory=list)
    FIO_IODEPTH: List[str] = Field(default_factory=list)
    FIO_NUMJOBS: List[str] = Field(default_factory=list)
    FIO_RWMIX: List[str] = Field(default_factory=list)
    FIO_EXTRA_OPTS: Optional[str] = None
    USE_BENCH_FIO: bool = True

    class Config:
        extra = "allow"  # allow unknown keys for forwards-compatibility


class ConnectionTestRequest(BaseModel):
    config: Dict[str, Any]


class StartBenchmarkRequest(BaseModel):
    config: Dict[str, Any]
    session_id: str = "default"


class StopBenchmarkRequest(BaseModel):
    session_id: str = "default"


class SystemInfoRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None


class GraidResetRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None


class SnapshotRequest(BaseModel):
    test_name: str
    output_dir: Optional[str] = None


class SaveSnapshotRequest(BaseModel):
    image: str  # base64-encoded PNG
    test_name: str
    output_dir: Optional[str] = None


# ---------------------------------------------------------------------------
# Helper — unified JSON response
# ---------------------------------------------------------------------------

def ok(data: Any = None, message: str = "OK") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return payload


def err(msg: str, status_code: int = 500) -> None:
    raise HTTPException(status_code=status_code, detail={"success": False, "error": msg})


# ---------------------------------------------------------------------------
# Config endpoints
# ---------------------------------------------------------------------------

@app.get(
    "/api/config",
    summary="Get current benchmark configuration",
    tags=["Config"],
    response_model=Dict[str, Any],
)
def get_config():
    """Return the current graid-bench.conf as JSON."""
    try:
        return ok(ConfigManager.load_config())
    except Exception as e:
        err(str(e))


@app.post(
    "/api/config",
    summary="Update benchmark configuration",
    tags=["Config"],
    response_model=Dict[str, Any],
    dependencies=[Depends(require_api_key)],
)
def update_config(payload: Dict[str, Any]):
    """Persist new configuration to graid-bench.conf.

    Send a partial or full config dict.  Unknown keys are stored as-is.
    """
    try:
        ConfigManager.save_config(payload)
        return ok(message="Config updated")
    except Exception as e:
        err(str(e))


# ---------------------------------------------------------------------------
# System-info endpoint
# ---------------------------------------------------------------------------

@app.get(
    "/api/system-info",
    summary="Collect hardware inventory and PCIe / GPU status",
    tags=["System"],
    response_model=Dict[str, Any],
)
@app.post(
    "/api/system-info",
    summary="Collect hardware inventory (with custom config)",
    tags=["System"],
    response_model=Dict[str, Any],
)
def get_system_info(body: Optional[SystemInfoRequest] = None):
    """
    Returns CPU, memory, NVMe device list (with PCIe link info), RAID
    controller info, and GPU performance state.

    POST with `{"config": {...}}` to query a remote DUT.
    """
    try:
        cpu_count = psutil.cpu_count(logical=False)
        cpu_freq = psutil.cpu_freq()
        memory = psutil.virtual_memory()

        config = (body.config if body and body.config else None) or ConfigManager.load_config()
        executor = RemoteExecutor(config)

        # NVMe devices
        nvme_info: List[Dict] = []
        try:
            res = executor.run(["graidctl", "ls", "nd", "--format", "json"], capture_output=True, text=True)
            if res.returncode == 0:
                start = res.stdout.find("{")
                if start != -1:
                    nvme_info = json.loads(res.stdout[start:]).get("Result", [])
        except Exception as e:
            logger.warning("graidctl nd failed: %s", e)

        # Augment with PCIe link data
        pcie_map = _collect_nvme_pcie_info(executor)
        for dev in nvme_info:
            dev_name = Path(dev.get("DevPath", "")).name
            dev.update(pcie_map.get(dev_name, {}))

        # RAID controller
        controller_info: List[Dict] = []
        try:
            res = executor.run(["graidctl", "ls", "cx", "--format", "json"], capture_output=True, text=True)
            if res.returncode == 0:
                start = res.stdout.find("{")
                if start != -1:
                    controller_info = json.loads(res.stdout[start:]).get("Result", [])
        except Exception as e:
            logger.warning("graidctl cx failed: %s", e)

        # GPU performance state
        gpu_perf = _collect_gpu_perf(executor)

        # Hostname
        hostname = "Unknown"
        try:
            res = executor.run(["hostname"], capture_output=True, text=True)
            if res.returncode == 0:
                hostname = res.stdout.strip()
        except Exception:
            pass

        return ok({
            "cpu_cores": cpu_count,
            "cpu_freq": cpu_freq.current if cpu_freq else None,
            "memory_gb": memory.total / (1024 ** 3),
            "memory_available_gb": memory.available / (1024 ** 3),
            "nvme_info": nvme_info,
            "controller_info": controller_info,
            "gpu_perf": gpu_perf,
            "hostname": hostname,
        })
    except Exception as e:
        err(str(e))


# ---------------------------------------------------------------------------
# License info
# ---------------------------------------------------------------------------

@app.get("/api/license-info", summary="Get GRAID license info", tags=["System"])
@app.post("/api/license-info", summary="Get GRAID license info (remote)", tags=["System"])
def get_license_info(body: Optional[SystemInfoRequest] = None):
    try:
        config = (body.config if body and body.config else None) or ConfigManager.load_config()
        executor = RemoteExecutor(config)
        license_info: Dict = {}
        try:
            res = executor.run(["graidctl", "desc", "lic", "--format", "json"], capture_output=True, text=True)
            if res.returncode == 0:
                start = res.stdout.find("{")
                if start != -1:
                    license_info = json.loads(res.stdout[start:]).get("Result", {})
        except Exception as e:
            logger.warning("graidctl lic failed: %s", e)
        return ok(license_info)
    except Exception as e:
        err(str(e))


# ---------------------------------------------------------------------------
# Benchmark control
# ---------------------------------------------------------------------------

@app.post(
    "/api/benchmark/test-connection",
    summary="Test DUT SSH connectivity and check dependencies",
    tags=["Benchmark"],
    dependencies=[Depends(require_api_key)],
)
def test_connection(body: ConnectionTestRequest):
    try:
        executor = RemoteExecutor(body.config)
        res = executor.run(["echo", "success"], capture_output=True, text=True)
        if res.returncode == 0:
            dep_results = executor.check_dependencies()
            missing = [d for d, present in dep_results.items() if not present]
            msg = "Connection established and permissions verified."
            if missing:
                msg += f" Missing dependencies: {', '.join(missing)}."
            return ok({"dependencies": dep_results}, message=msg)
        raise HTTPException(status_code=503, detail=f"Connection test failed: {res.stderr}")
    except HTTPException:
        raise
    except Exception as e:
        err(str(e))


@app.post(
    "/api/benchmark/setup-dut",
    summary="Install benchmark dependencies on the remote DUT",
    tags=["Benchmark"],
    dependencies=[Depends(require_api_key)],
)
def setup_dut(body: ConnectionTestRequest):
    try:
        executor = RemoteExecutor(body.config)
        if not executor.is_remote:
            raise HTTPException(status_code=400, detail="Target is local — no remote setup needed.")

        setup_script = BASE_DIR / "scripts" / "setup_env.sh"
        if not setup_script.exists():
            raise HTTPException(status_code=500, detail=f"Setup script not found: {setup_script}")

        executor.run(["mkdir", "-p", "/tmp/graid-setup"])
        executor.sync_to_remote(str(setup_script), "/tmp/graid-setup/setup_env.sh")
        res = executor.run(["bash", "/tmp/graid-setup/setup_env.sh"], capture_output=True, text=True)
        if res.returncode != 0:
            raise HTTPException(status_code=500, detail=res.stderr or "Setup script failed")
        return ok(message="DUT setup complete")
    except HTTPException:
        raise
    except Exception as e:
        err(str(e))


@app.post(
    "/api/benchmark/start",
    summary="Start the benchmark run",
    tags=["Benchmark"],
    dependencies=[Depends(require_api_key)],
)
def start_benchmark(body: StartBenchmarkRequest):
    if benchmark_manager.running:
        raise HTTPException(status_code=409, detail="Another benchmark is already running")
    try:
        thread = threading.Thread(
            target=benchmark_manager.run_benchmark,
            args=(body.config, body.session_id),
            daemon=True,
        )
        thread.start()
        return ok(message="Benchmark started")
    except Exception as e:
        err(str(e))


@app.post(
    "/api/benchmark/stop",
    summary="Stop the running benchmark",
    tags=["Benchmark"],
    dependencies=[Depends(require_api_key)],
)
def stop_benchmark(body: StopBenchmarkRequest):
    try:
        if benchmark_manager.process and benchmark_manager.running:
            benchmark_manager.process.terminate()
            time.sleep(1)
            if benchmark_manager.process.poll() is None:
                benchmark_manager.process.kill()
        BenchmarkState.clear()
        return ok(message="Benchmark stopped")
    except Exception as e:
        err(str(e))
    finally:
        benchmark_manager.running = False


@app.get(
    "/api/benchmark/status",
    summary="Get current benchmark run status",
    tags=["Benchmark"],
)
def get_benchmark_status():
    try:
        state = BenchmarkState.load()
        return ok({
            "running": benchmark_manager.running,
            "progress": benchmark_manager.latest_progress,
            "stage": benchmark_manager.current_stage_info,
            "active_state": state,
        })
    except Exception as e:
        err(str(e))


@app.get(
    "/api/benchmark/logs",
    summary="Get recent benchmark log lines",
    tags=["Benchmark"],
)
def get_benchmark_logs(lines: int = 100):
    try:
        log_file = None
        if benchmark_manager.process and benchmark_manager.current_log_file:
            log_file = benchmark_manager.current_log_file
        if not log_file and LOGS_DIR.exists():
            logs = sorted(LOGS_DIR.glob("benchmark_*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
            if logs:
                log_file = logs[0]
        if log_file and Path(log_file).exists():
            content = Path(log_file).read_text().splitlines()
            return ok({"logs": [l.strip() for l in content[-lines:]], "log_file": str(log_file)})
        return ok({"logs": [], "log_file": None})
    except Exception as e:
        err(str(e))


# ---------------------------------------------------------------------------
# GRAID resource management
# ---------------------------------------------------------------------------

@app.get(
    "/api/graid/check",
    summary="Check for existing GRAID VDs / DGs / PDs",
    tags=["GRAID"],
)
@app.post("/api/graid/check", summary="Check GRAID resources (remote)", tags=["GRAID"])
def check_graid_resources(body: Optional[GraidResetRequest] = None):
    try:
        config = (body.config if body and body.config else None) or ConfigManager.load_config()
        executor = RemoteExecutor(config)
        has_resources = False
        findings: List[str] = []

        for resource, label in [("vd", "VDs"), ("dg", "DGs"), ("pd", "PDs")]:
            res = executor.run(["graidctl", "ls", resource, "--format", "json"], capture_output=True, text=True)
            if res.returncode == 0:
                items = parse_graidctl_json(res.stdout).get("Result", [])
                if items:
                    has_resources = True
                    findings.append(f"{len(items)} {label}")

        return ok({"has_resources": has_resources, "findings": findings})
    except Exception as e:
        err(str(e))


@app.post(
    "/api/graid/reset",
    summary="Delete all GRAID VDs, DGs, and PDs",
    tags=["GRAID"],
    dependencies=[Depends(require_api_key)],
)
def reset_graid_resources(body: Optional[GraidResetRequest] = None):
    try:
        config = (body.config if body and body.config else None) or ConfigManager.load_config()
        executor = RemoteExecutor(config)
        deleted: List[str] = []

        # Delete VDs first, then DGs, then PDs
        for cmd_args, label in [
            (["graidctl", "del", "vd", "--all", "--force"], "VDs"),
            (["graidctl", "del", "dg", "--all", "--force"], "DGs"),
            (["graidctl", "del", "pd", "--all", "--force"], "PDs"),
        ]:
            res = executor.run(cmd_args, capture_output=True, text=True)
            if res.returncode == 0:
                deleted.append(label)

        return ok({"deleted": deleted}, message=f"Deleted: {', '.join(deleted) or 'nothing'}")
    except Exception as e:
        err(str(e))


# ---------------------------------------------------------------------------
# Results browsing
# ---------------------------------------------------------------------------

@app.get(
    "/api/results",
    summary="List available benchmark result directories",
    tags=["Results"],
)
def list_results():
    try:
        results = []
        temp_data = RESULTS_DIR / ".test-temp-data"
        scan_dirs = [temp_data] if temp_data.exists() else [RESULTS_DIR]

        for scan_dir in scan_dirs:
            for d in sorted(scan_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                if d.is_dir() and not d.name.startswith("."):
                    results.append({
                        "name": d.name,
                        "path": str(d.relative_to(RESULTS_DIR)),
                        "modified": datetime.fromtimestamp(d.stat().st_mtime).isoformat(),
                    })
        return ok(results)
    except Exception as e:
        err(str(e))


@app.get(
    "/api/results/{result_name}/data",
    summary="Get parsed benchmark result data",
    tags=["Results"],
)
def get_result_data(result_name: str):
    """Return structured benchmark metrics for a result directory."""
    # Security: block path traversal
    if ".." in result_name or result_name.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid result name")
    try:
        temp_data = RESULTS_DIR / ".test-temp-data"
        result_dir = (temp_data / result_name) if (temp_data / result_name).exists() else (RESULTS_DIR / result_name)
        if not result_dir.exists():
            raise HTTPException(status_code=404, detail=f"Result '{result_name}' not found")

        # Walk the result tree and collect all JSON data files
        data: Dict[str, Any] = {"result_name": result_name, "tests": []}
        for json_file in sorted(result_dir.rglob("*.json")):
            try:
                payload = json.loads(json_file.read_text())
                rel = json_file.relative_to(result_dir)
                data["tests"].append({"path": str(rel), "data": payload})
            except Exception:
                pass
        return ok(data)
    except HTTPException:
        raise
    except Exception as e:
        err(str(e))


@app.get(
    "/api/results/{result_name}/download",
    summary="Download result directory as .tar.gz",
    tags=["Results"],
)
def download_result(result_name: str):
    if ".." in result_name or result_name.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid result name")
    import tarfile, tempfile

    temp_data = RESULTS_DIR / ".test-temp-data"
    result_dir = (temp_data / result_name) if (temp_data / result_name).exists() else (RESULTS_DIR / result_name)
    if not result_dir.exists():
        raise HTTPException(status_code=404, detail="Result not found")

    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    try:
        with tarfile.open(tmp.name, "w:gz") as tar:
            tar.add(result_dir, arcname=result_name)
        return FileResponse(tmp.name, media_type="application/gzip", filename=f"{result_name}.tar.gz")
    except Exception as e:
        err(str(e))


# ---------------------------------------------------------------------------
# Snapshot endpoints (called by frontend chart capture)
# ---------------------------------------------------------------------------

@app.post("/api/benchmark/trigger_snapshot", summary="Request a chart snapshot", tags=["Benchmark"])
async def trigger_snapshot(body: SnapshotRequest):
    await sio.emit("snapshot_request", {"test_name": body.test_name, "output_dir": body.output_dir or ""})
    return ok(message="Snapshot requested")


@app.post("/api/benchmark/save_snapshot", summary="Save a base64-encoded chart snapshot", tags=["Benchmark"])
def save_snapshot(body: SaveSnapshotRequest):
    try:
        encoded = body.image.split(",", 1)[1] if "," in body.image else body.image
        image_binary = base64.b64decode(encoded)

        output_dir = body.output_dir or ""
        if ".." in output_dir:
            raise HTTPException(status_code=400, detail="Invalid path")
        for prefix in ("../results/", "./results/", "./"):
            if output_dir.startswith(prefix):
                output_dir = output_dir[len(prefix):]
                break

        save_dir = (RESULTS_DIR / output_dir / "report_view") if output_dir else (RESULTS_DIR / "report_view")
        save_dir.mkdir(parents=True, exist_ok=True)
        out_path = save_dir / f"{body.test_name}_report_view.png"
        out_path.write_bytes(image_binary)
        return ok({"saved_path": str(out_path)}, message="Snapshot saved")
    except HTTPException:
        raise
    except Exception as e:
        err(str(e))


# ---------------------------------------------------------------------------
# Log file browsing
# ---------------------------------------------------------------------------

@app.get("/api/logs", summary="List available benchmark log files", tags=["Logs"])
def list_logs():
    try:
        logs = sorted(LOGS_DIR.glob("*.log"), key=lambda x: x.stat().st_mtime, reverse=True)
        return ok([{"name": l.name, "size_kb": round(l.stat().st_size / 1024, 1),
                    "modified": datetime.fromtimestamp(l.stat().st_mtime).isoformat()} for l in logs])
    except Exception as e:
        err(str(e))


@app.get("/api/logs/{log_name}", summary="Get contents of a log file", tags=["Logs"])
def get_log(log_name: str, tail: int = 200):
    if ".." in log_name or log_name.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid log name")
    log_path = LOGS_DIR / log_name
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    lines = log_path.read_text(errors="replace").splitlines()
    return ok({"log_name": log_name, "lines": lines[-tail:], "total_lines": len(lines)})


# ---------------------------------------------------------------------------
# Socket.IO event handlers
# ---------------------------------------------------------------------------

@sio.event
async def connect(sid, environ):
    logger.info("Socket.IO client connected: %s", sid)


@sio.event
async def disconnect(sid):
    logger.info("Socket.IO client disconnected: %s", sid)


@sio.event
async def join(sid, data):
    """Client sends {'session_id': '...'} to subscribe to benchmark events."""
    session_id = data.get("session_id", "default")
    await sio.enter_room(sid, session_id)
    logger.info("Client %s joined room %s", sid, session_id)


# ---------------------------------------------------------------------------
# Entry point for direct execution
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "fastapi_app:combined_app",
        host="0.0.0.0",
        port=50073,
        reload=False,
        log_level="info",
    )
