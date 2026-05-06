"""Module-level constants, paths, logger, and the socketio placeholder.

`socketio` defaults to a no-op emitter. fastapi_app monkey-patches this
at startup with an adapter that forwards calls to its python-socketio
AsyncServer (see fastapi_app.on_startup).
"""

import json
import logging
import logging.handlers
import re
from pathlib import Path
from uuid import uuid4

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger('graid-bench')
audit_logger = logging.getLogger('graid-bench.audit')

SENSITIVE_CONFIG_KEYS = {'DUT_PASSWORD'}

WORKLOAD_MAP = {
    '00-randread': '4k Random Read',
    '01-seqread': '1M Sequential Read',
    '02-seqwrite': '1M Sequential Write',
    '09-randwrite': '4k Random Write',
}


class _NoopEmitter:
    """Default placeholder for `socketio`.

    fastapi_app replaces this on startup with `_SioAdapter`, which
    bridges sync calls from benchmark threads to the asyncio loop.
    Until then (and during isolated unit tests) emits silently no-op.
    """

    def emit(self, event, data=None, room=None, **kwargs):
        return None


socketio = _NoopEmitter()

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "graid-bench.conf"
SCRIPT_DIR = BASE_DIR / "scripts"

# Preference: Parent results (Local Dev) > Subfolder results (Existing/Docker)
if (BASE_DIR.parent / "results").exists():
    RESULTS_DIR = BASE_DIR.parent / "results"
    LOGS_DIR = BASE_DIR.parent / "logs"
else:
    RESULTS_DIR = BASE_DIR / "results"
    LOGS_DIR = BASE_DIR / "logs"

CACHE_DIR = RESULTS_DIR / ".cache"

RESULTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

if not any(isinstance(handler, logging.FileHandler) and getattr(handler, 'baseFilename', '').endswith('audit.log')
           for handler in audit_logger.handlers):
    # 10 MB per file, 5 rotations → ~50 MB upper bound on disk (CQ6 in AUDIT.md).
    audit_handler = logging.handlers.RotatingFileHandler(
        LOGS_DIR / 'audit.log',
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
    )
    audit_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    ))
    audit_logger.addHandler(audit_handler)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False


REMOTE_BASE_DIR = Path("/tmp/benchmark-gui")
ACTIVE_STATE_FILE = LOGS_DIR / "active_benchmark.json"

ANSI_ESCAPE = re.compile(r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])')


def strip_ansi(text):
    if not text:
        return text
    return ANSI_ESCAPE.sub('', text)


def generate_run_id():
    return f"run-{uuid4().hex[:12]}"


def audit_event(action, **details):
    payload = {'action': action, **details}
    audit_logger.info(json.dumps(payload, default=str, sort_keys=True))
