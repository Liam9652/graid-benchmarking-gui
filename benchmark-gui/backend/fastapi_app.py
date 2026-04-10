#!/usr/bin/env python3
"""GRAID Benchmark Web GUI — FastAPI backend."""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import os
import re
import secrets
import tarfile
import tempfile
import threading
import time
from contextvars import ContextVar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil
import socketio
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Security, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
from pydantic import BaseModel, Field

from app import (
    BASE_DIR,
    CACHE_DIR,
    LOGS_DIR,
    RESULTS_DIR,
    BenchmarkState,
    ConfigManager,
    RemoteExecutor,
    _collect_device_usage,
    _collect_gpu_perf,
    _collect_nvme_pcie_info,
    _extract_raid_from_cmd_dir,
    audit_event,
    benchmark_manager,
    generate_run_id,
    parse_graidctl_json,
    public_config,
    sanitize_config,
)


logger = logging.getLogger("fastapi-benchmark")

app = FastAPI(
    title="GRAID Benchmark GUI API",
    description=(
        "REST API for the GRAID Benchmark Web GUI. "
        "Provides configuration, benchmark control, results browsing, "
        "and real-time status via Socket.IO."
    ),
    version="1.1.0",
    contact={"name": "GRAID Technology"},
    license_info={"name": "Proprietary"},
)

_API_KEY: str | None = os.environ.get("BENCHMARK_API_KEY")
_raw_origins = os.environ.get(
    "BENCHMARK_ALLOWED_ORIGINS",
    "http://localhost:50072,http://127.0.0.1:50072,http://localhost:3000,http://127.0.0.1:3000",
)
_ALLOW_ALL_ORIGINS = _raw_origins.strip() == "*"
_ALLOWED_ORIGINS = (
    ["*"]
    if _ALLOW_ALL_ORIGINS
    else [o.strip() for o in _raw_origins.split(",") if o.strip()]
)

app.user_middleware.clear()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS or ["http://localhost:50072"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
)

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins="*" if _ALLOW_ALL_ORIGINS else (_ALLOWED_ORIGINS or ["http://localhost:50072"]),
)
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

combined_app = socketio.ASGIApp(sio, app)

# --- In-memory credential session store ---
_SESSION_TTL = timedelta(hours=24)
_credential_sessions: Dict[str, Dict] = {}  # token → {config, created_at}

def _purge_expired_sessions() -> None:
    cutoff = datetime.utcnow() - _SESSION_TTL
    expired = [t for t, s in _credential_sessions.items() if s["created_at"] < cutoff]
    for t in expired:
        del _credential_sessions[t]

MAX_SNAPSHOT_BYTES = 12 * 1024 * 1024
SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def require_api_key(key: str | None = Security(_api_key_header)) -> None:
    if _API_KEY and key != _API_KEY:
        audit_event("auth.failed", request_id=current_request_id(), reason="invalid_or_missing_api_key")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )


def require_socket_api_key(environ: Dict[str, Any], auth: Optional[Dict[str, Any]] = None) -> None:
    if not _API_KEY:
        return
    candidate = None
    if isinstance(auth, dict):
        candidate = auth.get("apiKey")
    if not candidate:
        header_value = environ.get("HTTP_X_API_KEY")
        candidate = header_value
    if candidate != _API_KEY:
        audit_event("socket.auth_failed", reason="invalid_or_missing_api_key")
        raise ConnectionRefusedError("Invalid or missing API key")


class ConnectionTestRequest(BaseModel):
    config: Dict[str, Any]


class StartBenchmarkRequest(BaseModel):
    config: Dict[str, Any]
    session_id: str = "default"


class StopBenchmarkRequest(BaseModel):
    run_id: Optional[str] = None


class SystemInfoRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None


class GraidResetRequest(BaseModel):
    config: Optional[Dict[str, Any]] = None


class SessionRestoreRequest(BaseModel):
    token: str


class SnapshotRequest(BaseModel):
    run_id: Optional[str] = None
    test_name: str
    output_dir: Optional[str] = None


class SaveSnapshotRequest(BaseModel):
    run_id: Optional[str] = None
    image: str
    test_name: str
    output_dir: Optional[str] = None


def ok(data: Any = None, message: str = "OK") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"success": True, "message": message}
    if data is not None:
        payload["data"] = data
    return payload


def err(msg: str, status_code: int = 500) -> None:
    raise HTTPException(status_code=status_code, detail={"success": False, "error": msg})


def current_request_id() -> str:
    return request_id_ctx.get()


def clean_name(value: str, default: str = "item") -> str:
    cleaned = SAFE_NAME_RE.sub("_", value.strip()).strip("._-")
    return cleaned[:160] or default


def normalize_relative_path(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.replace("\\", "/")
    for prefix in ("../results/", "./results/", "./"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix):]
            break
    normalized = normalized.strip("/")
    if not normalized:
        return ""
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        err("Invalid path", 400)
    return "/".join(parts)


def require_valid_result_name(result_name: str) -> str:
    if ".." in result_name or result_name.startswith("/"):
        err("Invalid result name", 400)
    return result_name


def get_effective_config(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    persisted = ConfigManager.load_config()
    merged = dict(persisted)
    if config:
        merged.update(config)
    return merged


def resolve_saved_state() -> Optional[Dict[str, Any]]:
    state = BenchmarkState.load()
    if not state:
        return None
    if benchmark_manager.running:
        return state
    run_id = state.get("run_id")
    if not run_id:
        return state
    return state


def resolve_active_run_id() -> Optional[str]:
    if benchmark_manager.active_run_id:
        return benchmark_manager.active_run_id
    state = resolve_saved_state()
    return state.get("run_id") if state else None


def clear_runtime_state() -> None:
    benchmark_manager.running = False
    benchmark_manager.active_run_id = None
    benchmark_manager.session_id = None
    benchmark_manager.runtime_config = None


def get_result_target(result_name: str) -> Path:
    require_valid_result_name(result_name)
    result_path = RESULTS_DIR / result_name
    if result_path.exists():
        return result_path
    for ext in (".tar", ".tar.gz", ".tgz", ".json"):
        archive = RESULTS_DIR / f"{result_name}{ext}"
        if archive.exists():
            return archive
    model_result = BASE_DIR / "scripts" / f"{result_name}-result" / result_name
    if model_result.exists():
        return model_result
    err("Result not found", 404)


def parse_basic_log(content: str) -> Dict[str, str]:
    result = {"graid_version": "N/A", "os_info": "N/A", "kernel_version": "N/A"}
    for line in content.splitlines():
        line = line.strip()
        if "graidctl version:" in line:
            result["graid_version"] = line.split(":", 1)[1].strip()
        elif line.startswith("OS:"):
            result["os_info"] = line.split(":", 1)[1].strip().replace('"', "")
        elif "PRETTY_NAME=" in line:
            result["os_info"] = line.split("=", 1)[1].strip().replace('"', "")
        elif line.startswith("Kernel version:"):
            result["kernel_version"] = line.split(":", 1)[1].strip()
    return result


def get_workload_name(row: Dict[str, str]) -> str:
    filename_col = row.get("filename", "")
    if "SingleTest" in filename_col:
        if "01-seqread" in filename_col:
            return "1M Sequential Read"
        if "02-seqwrite" in filename_col:
            return "1M Sequential Write"
    if "randrw73" in filename_col:
        return "4k Random Read/Write Mix(70/30)"

    bs_label = row.get("BlockSize", "")
    try:
        bs_float = float(bs_label)
    except Exception:
        bs_float = 0.0

    if bs_float == 4.0:
        size_label = "4k"
    elif bs_float == 1024.0:
        size_label = "1M"
    else:
        size_label = bs_label or "Unknown"

    row_type = (row.get("Type") or "").lower()
    type_label = {
        "randread": "Random Read",
        "read": "Sequential Read",
        "randwrite": "Random Write",
        "write": "Sequential Write",
    }.get(row_type, row_type or "Unknown")
    return f"{size_label} {type_label}".strip()


def parse_csv_rows(content: str, source_name: str, req_type: Optional[str]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    reader = csv.DictReader(content.splitlines())
    for row in reader:
        filename_col = row.get("filename") or row.get("file_name") or source_name
        if req_type == "baseline":
            if "SingleTest" not in filename_col and "/PD/" not in source_name.upper():
                continue
        elif req_type == "graid":
            if "RAID" not in filename_col and "/VD/" not in source_name.upper() and "/MD/" not in source_name.upper():
                continue

        row["Workload"] = row.get("Workload") or get_workload_name(row)
        row["controller"] = "MDADM" if "graid-mdadm" in filename_col else "SupremeRAID"
        if not row.get("RAID_type") or row.get("RAID_type") in ("N/A", ""):
            if req_type == "baseline":
                row["RAID_type"] = "SingleTest"
            else:
                for part in filename_col.split("-"):
                    if part.startswith("RAID"):
                        row["RAID_type"] = part
                        break
        rows.append(row)
    return rows


def collect_result_rows(result_name: str, req_type: Optional[str]) -> List[Dict[str, Any]]:
    target = get_result_target(result_name)
    csv_data: List[Dict[str, Any]] = []

    if target.is_dir():
        csv_files = list(target.rglob("*.csv"))
        filtered = csv_files
        if req_type == "baseline":
            filtered = [f for f in csv_files if "/PD/" in str(f) or "/pd/" in str(f)]
        elif req_type == "graid":
            filtered = [f for f in csv_files if "/VD/" in str(f) or "/vd/" in str(f) or "/MD/" in str(f)]

        target_csvs = [f for f in filtered if "fio-test" in f.name or "diskspd-test" in f.name] or filtered
        summary_csvs = [f for f in target_csvs if re.search(r"fio-test-r-", f.name)]
        if summary_csvs:
            target_csvs = summary_csvs

        for csv_file in target_csvs:
            try:
                content = csv_file.read_text(errors="ignore")
                rows = parse_csv_rows(content, str(csv_file), req_type)
                for row in rows:
                    if not row.get("RAID_type") or row.get("RAID_type") in ("N/A", ""):
                        raid = _extract_raid_from_cmd_dir(csv_file.parent.parent)
                        if raid:
                            row["RAID_type"] = raid
                csv_data.extend(rows)
            except Exception as exc:
                logger.warning("Error parsing %s: %s", csv_file, exc)
    elif target.is_file() and target.name.lower().endswith((".tar", ".tar.gz", ".tgz")):
        with tarfile.open(target, "r") as tar:
            members = [
                member for member in tar.getmembers()
                if member.name.endswith(".csv") and ("fio-test" in member.name or "diskspd-test" in member.name)
            ]
            summary = [m for m in members if "result/fio-test-r-" in m.name]
            if summary:
                members = summary

            for member in members:
                extracted = tar.extractfile(member)
                if not extracted:
                    continue
                try:
                    content = extracted.read().decode("utf-8", errors="ignore")
                    csv_data.extend(parse_csv_rows(content, member.name, req_type))
                except Exception as exc:
                    logger.warning("Error parsing tar member %s: %s", member.name, exc)
    else:
        err("No CSV data found", 404)

    if not csv_data:
        err("No CSV data found", 404)
    return csv_data


def collect_result_info(result_name: str) -> Dict[str, Any]:
    target = get_result_target(result_name)
    info_data: Dict[str, Any] = {}
    if target.is_dir():
        info_file = target / "system_info.json"
        if info_file.exists():
            try:
                return json.loads(info_file.read_text())
            except Exception:
                pass
        for log_file in target.rglob("basic.log"):
            try:
                info_data = parse_basic_log(log_file.read_text(errors="ignore"))
                if info_data.get("graid_version") != "N/A":
                    return info_data
            except Exception:
                continue
        return info_data

    if target.is_file() and target.name.lower().endswith((".tar", ".tar.gz", ".tgz")):
        with tarfile.open(target, "r") as tar:
            for member in tar.getmembers():
                if member.name.endswith("system_info.json"):
                    extracted = tar.extractfile(member)
                    if extracted:
                        return json.load(extracted)
            for member in tar.getmembers():
                if member.name.endswith("basic.log"):
                    extracted = tar.extractfile(member)
                    if extracted:
                        return parse_basic_log(extracted.read().decode("utf-8", errors="ignore"))
    return info_data


def parse_image_tags(image_path: str) -> Dict[str, str]:
    filename = Path(image_path).stem
    tags = {
        "category": "VD" if "/VD/" in image_path else "MD" if "/MD/" in image_path else "PD" if "/PD/" in image_path else "Other",
        "raid": "Unknown",
        "workload": "Unknown",
        "bs": "Unknown",
        "status": "Normal",
    }
    for part in filename.split("-"):
        if part.startswith("RAID"):
            tags["raid"] = part.replace("RAID", "RAID ")
    if "Rebuild" in filename:
        tags["status"] = "Rebuild"
    if "seqwrite" in filename:
        tags["workload"] = "Seq Write"
    elif "seqread" in filename:
        tags["workload"] = "Seq Read"
    elif "randread" in filename:
        tags["workload"] = "Rand Read"
    elif "randwrite" in filename:
        tags["workload"] = "Rand Write"
    elif "randrw73" in filename:
        tags["workload"] = "Mix(70/30)"

    for block_size in ("4k", "8k", "16k", "32k", "64k", "128k", "256k", "512k", "1m", "2m", "4m"):
        if f"-{block_size}-" in filename or filename.endswith(f"-{block_size}") or f"_{block_size}_" in filename:
            tags["bs"] = block_size.upper()
            break
    if tags["category"] == "PD":
        tags["raid"] = "BASELINE"
    return tags


def collect_result_images(result_name: str) -> List[Dict[str, Any]]:
    target = get_result_target(result_name)
    images: List[Dict[str, Any]] = []
    if target.is_dir():
        for image in target.rglob("*"):
            if image.is_file() and image.suffix.lower() in (".png", ".jpg", ".jpeg") and "report_view" in str(image):
                rel_path = str(image.relative_to(RESULTS_DIR if str(image).startswith(str(RESULTS_DIR)) else BASE_DIR))
                images.append({
                    "name": image.name,
                    "url": f"/api/result-files/{rel_path}",
                    "tags": parse_image_tags(str(image)),
                })
    elif target.is_file() and target.name.lower().endswith((".tar", ".tar.gz", ".tgz")):
        cache_dir = CACHE_DIR / clean_name(result_name)
        cache_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "r") as tar:
            for member in tar.getmembers():
                if member.isfile() and member.name.lower().endswith((".png", ".jpg", ".jpeg")) and "report_view" in member.name:
                    cache_name = clean_name(member.name.replace("/", "_"), "image")
                    cache_file = cache_dir / cache_name
                    if not cache_file.exists():
                        extracted = tar.extractfile(member)
                        if extracted:
                            cache_file.write_bytes(extracted.read())
                    images.append({
                        "name": cache_name,
                        "url": f"/api/result-files/.cache/{cache_dir.name}/{cache_name}",
                        "tags": parse_image_tags(member.name),
                    })
    return images


def list_result_entries() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    if not RESULTS_DIR.exists():
        return results
    for item in RESULTS_DIR.iterdir():
        if item.name.startswith("."):
            continue
        if item.is_file() and item.name.lower().endswith((".tar", ".tar.gz", ".tgz", ".json")):
            results.append({
                "name": item.name,
                "type": "archive",
                "created": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                "size": item.stat().st_size,
            })
        elif item.is_dir():
            has_csv = any(item.rglob("*.csv"))
            is_result_folder = item.name.endswith("-result")
            if has_csv or is_result_folder:
                results.append({
                    "name": item.name,
                    "type": "folder",
                    "created": datetime.fromtimestamp(item.stat().st_mtime).isoformat(),
                    "files": [],
                })
    results.sort(key=lambda entry: entry["created"], reverse=True)
    return results


@app.get("/api/config", tags=["Config"])
def get_config():
    config = ConfigManager.load_config()
    return ok(sanitize_config(config))


@app.middleware("http")
async def audit_requests(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or generate_run_id()
    token = request_id_ctx.set(request_id)
    start = time.time()
    response = None
    try:
        response = await call_next(request)
        return response
    except HTTPException as exc:
        audit_event(
            "http.error",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=exc.status_code,
            client=request.client.host if request.client else None,
        )
        detail = exc.detail
        if isinstance(detail, dict):
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(detail)})
    except Exception as exc:
        audit_event(
            "http.exception",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            error=str(exc),
            client=request.client.host if request.client else None,
        )
        return JSONResponse(status_code=500, content={"success": False, "error": "Internal server error"})
    finally:
        duration_ms = round((time.time() - start) * 1000, 2)
        if response is not None:
            response.headers["X-Request-ID"] = request_id
            if request.method != "GET" or request.url.path.startswith("/api/benchmark") or request.url.path.startswith("/api/graid"):
                audit_event(
                    "http.request",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    client=request.client.host if request.client else None,
                )
        request_id_ctx.reset(token)


@app.post("/api/config", tags=["Config"], dependencies=[Depends(require_api_key)])
def update_config(payload: Dict[str, Any]):
    ConfigManager.save_config(payload)
    audit_event("config.update", config=public_config(payload))
    return ok(sanitize_config(ConfigManager.load_config()), message="Config updated")


@app.get("/api/system-info", tags=["System"])
@app.post("/api/system-info", tags=["System"])
def get_system_info(body: Optional[SystemInfoRequest] = None):
    cpu_count = psutil.cpu_count(logical=False)
    cpu_freq = psutil.cpu_freq()
    memory = psutil.virtual_memory()
    config = get_effective_config(body.config if body else None)
    executor = RemoteExecutor(config)

    nvme_info: List[Dict[str, Any]] = []
    try:
        res = executor.run(["graidctl", "ls", "nd", "--format", "json"], capture_output=True, text=True)
        if res.returncode == 0:
            start = res.stdout.find("{")
            if start != -1:
                nvme_info = json.loads(res.stdout[start:]).get("Result", [])
    except Exception as exc:
        logger.warning("graidctl nd failed: %s", exc)

    pcie_map = _collect_nvme_pcie_info(executor)
    usage_map = _collect_device_usage(executor)
    for dev in nvme_info:
        dev_name = Path(dev.get("DevPath", "")).name
        dev.update(pcie_map.get(dev_name, {}))
        reasons = usage_map.get(dev_name)
        if reasons:
            dev["in_use"] = True
            dev["use_reasons"] = reasons

    controller_info: List[Dict[str, Any]] = []
    try:
        res = executor.run(["graidctl", "ls", "cx", "--format", "json"], capture_output=True, text=True)
        if res.returncode == 0:
            start = res.stdout.find("{")
            if start != -1:
                controller_info = json.loads(res.stdout[start:]).get("Result", [])
    except Exception as exc:
        logger.warning("graidctl cx failed: %s", exc)

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
        "gpu_perf": _collect_gpu_perf(executor),
        "hostname": hostname,
    })


@app.get("/api/license-info", tags=["System"])
@app.post("/api/license-info", tags=["System"])
def get_license_info(body: Optional[SystemInfoRequest] = None):
    config = get_effective_config(body.config if body else None)
    executor = RemoteExecutor(config)
    license_info: Dict[str, Any] = {}
    try:
        res = executor.run(["graidctl", "desc", "lic", "--format", "json"], capture_output=True, text=True)
        if res.returncode == 0:
            start = res.stdout.find("{")
            if start != -1:
                license_info = json.loads(res.stdout[start:]).get("Result", {})
    except Exception as exc:
        logger.warning("graidctl lic failed: %s", exc)
    return ok(license_info)


@app.post("/api/benchmark/test-connection", tags=["Benchmark"], dependencies=[Depends(require_api_key)])
def test_connection(body: ConnectionTestRequest):
    executor = RemoteExecutor(body.config)
    res = executor.run(["echo", "success"], capture_output=True, text=True)
    if res.returncode != 0:
        err(f"Connection test failed: {res.stderr}", 503)
    dep_results = executor.check_dependencies()
    missing = [name for name, present in dep_results.items() if not present]
    message = "Connection established and permissions verified."
    if missing:
        message += f" Missing dependencies: {', '.join(missing)}."
    audit_event("dut.test_connection", remote=body.config.get("REMOTE_MODE", False), target=body.config.get("DUT_IP"))
    # Issue a session token so the frontend can restore credentials on page refresh
    _purge_expired_sessions()
    session_token = secrets.token_urlsafe(32)
    _credential_sessions[session_token] = {
        "config": dict(body.config),
        "created_at": datetime.utcnow(),
    }
    return ok({"dependencies": dep_results, "session_token": session_token}, message=message)


@app.post("/api/session/restore", tags=["Session"], dependencies=[Depends(require_api_key)])
def restore_session(body: SessionRestoreRequest):
    _purge_expired_sessions()
    session = _credential_sessions.get(body.token)
    if not session:
        err("Session expired or invalid", 401)
    config = session["config"]
    executor = RemoteExecutor(config)
    try:
        res = executor.run(["echo", "ok"], capture_output=True, text=True)
        if res.returncode != 0:
            raise ConnectionError("SSH echo check failed")
    except Exception as e:
        _credential_sessions.pop(body.token, None)
        err(f"Session invalid: {e}", 401)
    # Refresh TTL on successful restore
    session["created_at"] = datetime.utcnow()
    dep_results = executor.check_dependencies()
    missing = [name for name, present in dep_results.items() if not present]
    message = "Session restored."
    if missing:
        message += f" Missing dependencies: {', '.join(missing)}."
    audit_event("session.restore", target=config.get("DUT_IP"))
    return ok({"config": config, "dependencies": dep_results}, message=message)


@app.post("/api/benchmark/setup-dut", tags=["Benchmark"], dependencies=[Depends(require_api_key)])
def setup_dut(body: ConnectionTestRequest):
    executor = RemoteExecutor(body.config)
    if not executor.is_remote:
        err("Target is local — no remote setup needed.", 400)

    setup_script = BASE_DIR / "scripts" / "setup_env.sh"
    if not setup_script.exists():
        err(f"Setup script not found: {setup_script}")

    executor.run(["mkdir", "-p", "/tmp/graid-setup"])
    executor.sync_to_remote(str(setup_script), "/tmp/graid-setup/setup_env.sh")
    res = executor.run(["bash", "/tmp/graid-setup/setup_env.sh", "--dut-mode"], capture_output=True, text=True)
    if res.returncode != 0:
        audit_event("dut.setup_failed", target=body.config.get("DUT_IP"), stderr=res.stderr)
        err(res.stderr or "Setup script failed")
    audit_event("dut.setup_complete", target=body.config.get("DUT_IP"))
    return ok({"details": res.stdout}, message="DUT setup complete")


@app.post("/api/benchmark/start", tags=["Benchmark"], dependencies=[Depends(require_api_key)])
def start_benchmark(body: StartBenchmarkRequest):
    if benchmark_manager.running:
        err("Another benchmark is already running", 409)
    run_id = generate_run_id()
    thread = threading.Thread(
        target=benchmark_manager.run_benchmark,
        args=(body.config, body.session_id, run_id),
        daemon=True,
    )
    thread.start()
    audit_event(
        "benchmark.start",
        run_id=run_id,
        session_id=body.session_id,
        config=public_config(body.config),
    )
    return ok({"run_id": run_id}, message="Benchmark started")


@app.post("/api/benchmark/stop", tags=["Benchmark"], dependencies=[Depends(require_api_key)])
def stop_benchmark(body: StopBenchmarkRequest):
    active_run_id = resolve_active_run_id()
    if body.run_id and active_run_id and body.run_id != active_run_id:
        err("Run ID does not match the active benchmark", 409)
    try:
        if benchmark_manager.process and benchmark_manager.running:
            benchmark_manager.process.terminate()
            time.sleep(1)
            if benchmark_manager.process.poll() is None:
                benchmark_manager.process.kill()
        BenchmarkState.clear()
        audit_event("benchmark.stop", run_id=active_run_id)
        return ok({"run_id": active_run_id}, message="Benchmark stopped")
    finally:
        clear_runtime_state()


@app.get("/api/benchmark/status", tags=["Benchmark"])
def get_benchmark_status():
    saved_state = resolve_saved_state()
    return ok({
        "running": benchmark_manager.running,
        "run_id": resolve_active_run_id(),
        "progress": benchmark_manager.latest_progress,
        "stage_info": benchmark_manager.current_stage_info,
        "session_id": benchmark_manager.session_id or (saved_state or {}).get("session_id"),
        "active_state": saved_state,
    })


@app.get("/api/benchmark/logs", tags=["Benchmark"])
def get_benchmark_logs(lines: int = Query(default=100, ge=1, le=500)):
    log_file = benchmark_manager.current_log_file
    if not log_file and LOGS_DIR.exists():
        logs = sorted(LOGS_DIR.glob("benchmark_*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
        if logs:
            log_file = logs[0]
    if log_file and Path(log_file).exists():
        content = Path(log_file).read_text(errors="replace").splitlines()
        return {"success": True, "logs": [line.strip() for line in content[-lines:]], "log_file": str(log_file)}
    return {"success": True, "logs": [], "log_file": None}


@app.post("/api/graid/check", tags=["GRAID"])
def check_graid_resources(body: Optional[GraidResetRequest] = None):
    config = get_effective_config(body.config if body else None)
    executor = RemoteExecutor(config)
    has_resources = False
    findings: List[str] = []
    for resource, label in (("vd", "VDs"), ("dg", "DGs"), ("pd", "PDs")):
        res = executor.run(["graidctl", "ls", resource, "--format", "json"], capture_output=True, text=True)
        if res.returncode == 0:
            items = parse_graidctl_json(res.stdout).get("Result", [])
            if items:
                has_resources = True
                findings.append(f"{len(items)} {label}")
    return {"success": True, "has_resources": has_resources, "findings": findings}


@app.post("/api/graid/reset", tags=["GRAID"], dependencies=[Depends(require_api_key)])
def reset_graid_resources(body: Optional[GraidResetRequest] = None):
    if benchmark_manager.running:
        err("Cannot reset while benchmark is running", 400)
    config = get_effective_config(body.config if body else None)
    executor = RemoteExecutor(config)
    details: List[str] = []

    # 1. Delete VDs
    res = executor.run(["graidctl", "ls", "vd", "--format", "json"], capture_output=True, text=True)
    if res.returncode == 0:
        try:
            vds = parse_graidctl_json(res.stdout).get("Result", [])
            for vd in vds:
                dg_id = vd.get("DgId")
                vd_id = vd.get("VdId")
                if dg_id is not None and vd_id is not None:
                    del_res = executor.run(
                        ["graidctl", "del", "vd", str(dg_id), str(vd_id), "--confirm-to-delete"],
                        capture_output=True, text=True,
                    )
                    logger.info("VD %s/%s delete rc=%s: %s", dg_id, vd_id, del_res.returncode,
                                del_res.stdout.strip() or del_res.stderr.strip())
                    details.append(f"VD dg={dg_id} vd={vd_id}")
        except Exception as exc:
            logger.error("VD delete error: %s", exc)

    # 2. Delete DGs
    res = executor.run(["graidctl", "ls", "dg", "--format", "json"], capture_output=True, text=True)
    if res.returncode == 0:
        try:
            dgs = parse_graidctl_json(res.stdout).get("Result", [])
            for dg in dgs:
                dg_id = dg.get("DgId")
                if dg_id is not None:
                    del_res = executor.run(
                        ["graidctl", "del", "dg", str(dg_id), "--confirm-to-delete"],
                        capture_output=True, text=True,
                    )
                    logger.info("DG %s delete rc=%s: %s", dg_id, del_res.returncode,
                                del_res.stdout.strip() or del_res.stderr.strip())
                    details.append(f"DG dg={dg_id}")
        except Exception as exc:
            logger.error("DG delete error: %s", exc)

    # 3. Delete PDs
    res = executor.run(["graidctl", "ls", "pd", "--format", "json"], capture_output=True, text=True)
    if res.returncode == 0:
        try:
            pds = parse_graidctl_json(res.stdout).get("Result", [])
            pd_ids = [p.get("PdId") for p in pds if p.get("PdId") is not None]
            if pd_ids:
                pd_range = f"{min(pd_ids)}-{max(pd_ids)}"
                del_res = executor.run(
                    ["graidctl", "del", "pd", pd_range],
                    capture_output=True, text=True,
                )
                logger.info("PD range %s delete rc=%s: %s", pd_range, del_res.returncode,
                            del_res.stdout.strip() or del_res.stderr.strip())
                details.append(f"PDs {pd_range}")
        except Exception as exc:
            logger.error("PD delete error: %s", exc)

    audit_event("graid.reset", target=config.get("DUT_IP"), details=details)
    return ok({"details": details}, message=f"Reset complete: {', '.join(details) or 'nothing to delete'}")


@app.get("/api/results", tags=["Results"])
def list_results():
    return ok(list_result_entries())


@app.get("/api/results/{result_name}/info", tags=["Results"])
def get_result_info(result_name: str):
    return ok(collect_result_info(result_name))


@app.get("/api/results/{result_name}/data", tags=["Results"])
def get_result_data(result_name: str, type: Optional[str] = Query(default=None)):
    return ok(collect_result_rows(result_name, type))


@app.get("/api/results/{result_name}/images", tags=["Results"])
def get_result_images(result_name: str):
    return {"success": True, "images": collect_result_images(result_name)}


@app.post("/api/results/{result_name}/clear-cache", tags=["Results"], dependencies=[Depends(require_api_key)])
def clear_result_cache(result_name: str):
    target = CACHE_DIR / clean_name(result_name)
    if target.exists():
        import shutil

        shutil.rmtree(target)
    audit_event("results.clear_cache", result_name=result_name)
    return ok()


@app.get("/api/results/{result_name}/download", tags=["Results"])
def download_result(result_name: str):
    target = get_result_target(result_name)
    if target.is_file():
        return FileResponse(target, filename=target.name)

    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    with tarfile.open(tmp.name, "w:gz") as tar:
        tar.add(target, arcname=target.name)
    return FileResponse(tmp.name, media_type="application/gzip", filename=f"{target.name}.tar.gz")


@app.get("/api/result-files/{filename:path}", tags=["Results"])
def get_result_file(filename: str):
    normalized = normalize_relative_path(filename)
    candidates = [
        (RESULTS_DIR / normalized).resolve(),
        (BASE_DIR / normalized).resolve(),
        (CACHE_DIR.parent / normalized).resolve(),
    ]
    allowed_roots = [RESULTS_DIR.resolve(), CACHE_DIR.resolve(), BASE_DIR.resolve()]
    target = next((candidate for candidate in candidates if candidate.exists()), None)
    if target is None:
        err("Result file not found", 404)
    if not any(str(target).startswith(str(root)) for root in allowed_roots) or not target.exists():
        err("Result file not found", 404)
    return FileResponse(target)


@app.post("/api/benchmark/trigger_snapshot", tags=["Benchmark"], dependencies=[Depends(require_api_key)])
async def trigger_snapshot(body: SnapshotRequest):
    active_run_id = resolve_active_run_id()
    if body.run_id and active_run_id and body.run_id != active_run_id:
        err("Run ID does not match the active benchmark", 409)
    await sio.emit(
        "snapshot_request",
        {
            "run_id": body.run_id or active_run_id,
            "test_name": clean_name(body.test_name, "snapshot"),
            "output_dir": normalize_relative_path(body.output_dir),
        },
        room=benchmark_manager.session_id or "default",
    )
    audit_event("snapshot.trigger", run_id=body.run_id or active_run_id)
    return ok(message="Snapshot requested")


@app.post("/api/benchmark/save_snapshot", tags=["Benchmark"], dependencies=[Depends(require_api_key)])
def save_snapshot(body: SaveSnapshotRequest):
    active_run_id = resolve_active_run_id()
    if body.run_id and active_run_id and body.run_id != active_run_id:
        err("Run ID does not match the active benchmark", 409)

    encoded = body.image.split(",", 1)[1] if "," in body.image else body.image
    image_binary = base64.b64decode(encoded)
    if len(image_binary) > MAX_SNAPSHOT_BYTES:
        err("Snapshot too large", 413)

    output_dir = normalize_relative_path(body.output_dir)
    save_dir = (RESULTS_DIR / output_dir / "report_view") if output_dir else (RESULTS_DIR / "report_view")
    save_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{clean_name(body.test_name, 'snapshot')}_report_view.png"
    out_path = save_dir / filename
    out_path.write_bytes(image_binary)
    audit_event("snapshot.save", run_id=body.run_id or active_run_id, path=str(out_path.relative_to(RESULTS_DIR)))
    return ok({"saved_path": str(out_path)}, message="Snapshot saved")


@app.get("/api/logs", tags=["Logs"])
def list_logs():
    logs = sorted(LOGS_DIR.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)
    return ok([
        {
            "name": log_file.name,
            "size_kb": round(log_file.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(log_file.stat().st_mtime).isoformat(),
        }
        for log_file in logs
    ])


@app.get("/api/logs/{log_name}", tags=["Logs"])
def get_log(log_name: str, tail: int = Query(default=200, ge=1, le=2000)):
    if ".." in log_name or log_name.startswith("/"):
        err("Invalid log name", 400)
    log_path = LOGS_DIR / log_name
    if not log_path.exists():
        err("Log file not found", 404)
    lines = log_path.read_text(errors="replace").splitlines()
    return ok({"log_name": log_name, "lines": lines[-tail:], "total_lines": len(lines)})


@sio.event
async def connect(sid, environ, auth=None):
    require_socket_api_key(environ, auth)
    logger.info("Socket.IO client connected: %s", sid)


@sio.event
async def disconnect(sid):
    logger.info("Socket.IO client disconnected: %s", sid)


async def _join_room(sid: str, data: Dict[str, Any]):
    session_id = data.get("session_id", "default")
    sio.enter_room(sid, session_id)
    logger.info("Client %s joined room %s", sid, session_id)


@sio.event
async def join(sid, data):
    await _join_room(sid, data)


@sio.event
async def join_session(sid, data):
    await _join_room(sid, data)


@app.on_event("startup")
async def on_startup():
    import asyncio
    import app as _app_module

    # Bridge: replace app.py's Flask-SocketIO instance with an adapter that
    # forwards emit() calls to the real python-socketio AsyncServer (sio).
    # Benchmark threads call socketio.emit(...) synchronously; this adapter
    # schedules the coroutine on the running asyncio event loop.
    loop = asyncio.get_running_loop()

    class _SioAdapter:
        def emit(self, event, data=None, room=None, **kwargs):
            asyncio.run_coroutine_threadsafe(
                sio.emit(event, data, room=room),
                loop,
            )

    _app_module.socketio = _SioAdapter()

    state = BenchmarkState.load()
    if state:
        try:
            benchmark_manager.recover_state(state)
            audit_event("benchmark.recover_attempt", run_id=state.get("run_id"), session_id=state.get("session_id"))
        except Exception as exc:
            logger.warning("Benchmark state recovery failed: %s", exc)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "fastapi_app:combined_app",
        host="0.0.0.0",
        port=50071,
        reload=False,
        log_level="info",
    )
