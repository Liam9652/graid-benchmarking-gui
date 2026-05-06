#!/usr/bin/env python3
"""Compatibility shim re-exporting symbols from the split modules.

The historical app.py was a 2800-line monolith. After A1 (Flask retired)
and CQ1 (file split) it now re-exports from:

    config.py   — paths, logger, socketio placeholder, helpers
    state.py    — BenchmarkState, ConfigManager, sanitize/public_config
    executor.py — RemoteExecutor, _AutoUpdateHostKeyPolicy
    parsers.py  — _collect_*, parse_graidctl_json, _extract_raid_from_cmd_dir
    monitor.py  — giostat watchdog
    manager.py  — BenchmarkManager + benchmark_manager singleton

fastapi_app.py imports from `app`; this shim preserves those names so
the FastAPI side does not need to change. New code should import from
the specific modules instead.
"""

from config import (
    ACTIVE_STATE_FILE,
    ANSI_ESCAPE,
    BASE_DIR,
    CACHE_DIR,
    CONFIG_FILE,
    LOGS_DIR,
    REMOTE_BASE_DIR,
    RESULTS_DIR,
    SCRIPT_DIR,
    SENSITIVE_CONFIG_KEYS,
    WORKLOAD_MAP,
    _NoopEmitter,
    audit_event,
    audit_logger,
    generate_run_id,
    logger,
    socketio,
    strip_ansi,
)
from state import (
    BenchmarkState,
    ConfigManager,
    public_config,
    sanitize_config,
)
from executor import (
    RemoteExecutor,
    _AutoUpdateHostKeyPolicy,
)
from parsers import (
    _PCIE_INFO_CMD,
    _collect_device_usage,
    _collect_gpu_perf,
    _collect_nvme_pcie_info,
    _extract_raid_from_cmd_dir,
    parse_graidctl_json,
)
from monitor import (
    monitor_giostat,
    start_giostat_monitoring,
    stop_giostat_monitoring,
)
from manager import (
    BenchmarkManager,
    benchmark_manager,
    is_remote_benchmark_alive,
)

# `json` is referenced via `app.json` by tests/test_state.py to swap
# json.dump for fault injection. Keep the alias available.
import json  # noqa: F401  (used as `app.json` by test_state.py)
