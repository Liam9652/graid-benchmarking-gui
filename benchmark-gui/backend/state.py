"""Persistent state and config loader.

BenchmarkState writes ACTIVE_STATE_FILE atomically (B19 in AUDIT.md).
ConfigManager reads/writes the .conf file. sanitize_config / public_config
strip or redact DUT_PASSWORD before crossing trust boundaries.

All file-path references go through `config` module attributes (not
local imports) so tests can redirect `config.LOGS_DIR` /
`config.ACTIVE_STATE_FILE` to a tmp_path without re-importing this module.
"""

import json
import os

import config
from config import logger


class BenchmarkState:
    @staticmethod
    def save(state):
        try:
            config.LOGS_DIR.mkdir(exist_ok=True)
            tmp_path = config.ACTIVE_STATE_FILE.with_suffix(config.ACTIVE_STATE_FILE.suffix + '.tmp')
            with open(tmp_path, 'w') as f:
                json.dump(state, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, config.ACTIVE_STATE_FILE)
        except Exception as e:
            logger.error("Error saving benchmark state: %s", e)

    @staticmethod
    def load():
        try:
            if config.ACTIVE_STATE_FILE.exists():
                with open(config.ACTIVE_STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            logger.error("Error loading benchmark state: %s", e)
        return None

    @staticmethod
    def clear():
        try:
            if config.ACTIVE_STATE_FILE.exists():
                config.ACTIVE_STATE_FILE.unlink()
        except Exception as e:
            logger.error("Error clearing benchmark state: %s", e)


class ConfigManager:
    @staticmethod
    def load_config():
        cfg = {}
        if config.CONFIG_FILE.exists():
            with open(config.CONFIG_FILE, 'r') as f:
                cfg = json.load(f)
        return cfg

    @staticmethod
    def save_config(cfg):
        sanitized = {
            key: value for key, value in cfg.items()
            if key not in config.SENSITIVE_CONFIG_KEYS
        }
        with open(config.CONFIG_FILE, 'w') as f:
            json.dump(sanitized, f, indent=2)


def sanitize_config(cfg):
    if not isinstance(cfg, dict):
        return {}
    return {
        key: value for key, value in cfg.items()
        if key not in config.SENSITIVE_CONFIG_KEYS
    }


def public_config(cfg):
    redacted = dict(sanitize_config(cfg))
    if isinstance(cfg, dict) and cfg.get('DUT_PASSWORD'):
        redacted['DUT_PASSWORD'] = '***'
    return redacted
