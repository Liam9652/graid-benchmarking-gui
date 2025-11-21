#!/usr/bin/env python3
"""GRAID Benchmark Web GUI - Flask Backend"""

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
import subprocess
import json
import os
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
import psutil
import tarfile
import re
import shlex

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

print(f"DEBUG: __file__ = {__file__}")
print(f"DEBUG: __file__ resolved = {Path(__file__).resolve()}")
print(f"DEBUG: parent = {Path(__file__).resolve().parent}")
print(f"DEBUG: parent.parent = {Path(__file__).resolve().parent.parent}")
print(f"DEBUG: Current working dir = {os.getcwd()}")
print(f"DEBUG: Files in cwd = {os.listdir('.')}")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "graid-bench.conf"
SCRIPT_DIR = BASE_DIR / "scripts"
RESULTS_DIR = BASE_DIR / "results"
LOGS_DIR = BASE_DIR / "logs"

RESULTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

benchmark_process = None
benchmark_running = False


class ConfigManager:
    @staticmethod
    def load_config():
        config = {}
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
        return config

    @staticmethod
    def save_config(config):
        with open(CONFIG_FILE, 'w') as f:
            json.dump(config, f, indent=2)


class BenchmarkManager:
    def __init__(self):
        self.process = None
        self.running = False

    def run_benchmark(self, config, session_id):
        global benchmark_running, benchmark_process
        try:
            ConfigManager.save_config(config)
            benchmark_running = True
            target_config = SCRIPT_DIR / "graid-bench.conf"
            shutil.copy(CONFIG_FILE, target_config)
            socketio.emit('status', {
                'status': 'started',
                'message': 'Benchmark started',
                'timestamp': datetime.now().isoformat()
            }, room=session_id)

            log_file = LOGS_DIR / f"benchmark_{int(time.time())}.log"
            cmd = ['bash', str(SCRIPT_DIR / 'graid-bench.sh')]

            with open(log_file, 'w') as log:
                self.process = subprocess.Popen(
                    cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(
                        SCRIPT_DIR)
                )
                benchmark_process = self.process

                while self.process.poll() is None:
                    socketio.emit('progress', {
                        'status': 'running',
                        'message': 'Benchmark running...',
                        'timestamp': datetime.now().isoformat()
                    }, room=session_id)
                    time.sleep(5)

            if self.process.returncode == 0:
                socketio.emit('status', {
                    'status': 'completed',
                    'message': 'Benchmark completed',
                    'timestamp': datetime.now().isoformat()
                }, room=session_id)
            else:
                socketio.emit('status', {
                    'status': 'failed',
                    'message': f'Failed: {self.process.returncode}',
                    'timestamp': datetime.now().isoformat()
                }, room=session_id)
        except Exception as e:
            socketio.emit('error', {
                'message': str(e),
                'timestamp': datetime.now().isoformat()
            }, room=session_id)
        finally:
            benchmark_running = False


benchmark_manager = BenchmarkManager()

# API 路由


@app.route('/api/config', methods=['GET'])
def get_config():
    try:
        config = ConfigManager.load_config()
        return jsonify({'success': True, 'data': config})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/config', methods=['POST'])
def update_config():
    try:
        data = request.json
        ConfigManager.save_config(data)
        return jsonify({'success': True, 'message': 'Config updated'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/system-info', methods=['GET'])
def get_system_info():
    try:
        cpu_count = psutil.cpu_count(logical=False)
        cpu_freq = psutil.cpu_freq()
        memory = psutil.virtual_memory()
        nvme_devices = []
        for device in os.listdir('/dev'):
            if device.startswith('nvme') and device.endswith('n1'):
                nvme_devices.append(device)

        return jsonify({
            'success': True,
            'data': {
                'cpu_cores': cpu_count,
                'cpu_freq': cpu_freq.current if cpu_freq else None,
                'memory_gb': memory.total / (1024**3),
                'memory_available_gb': memory.available / (1024**3),
                'nvme_devices': nvme_devices
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/benchmark/start', methods=['POST'])
def start_benchmark():
    global benchmark_running
    if benchmark_running:
        return jsonify({'success': False, 'error': 'Another benchmark is already running'}), 400

    try:
        data = request.json
        session_id = data.get('session_id', 'default')
        config = data.get('config', ConfigManager.load_config())

        thread = threading.Thread(
            target=benchmark_manager.run_benchmark,
            args=(config, session_id)
        )
        thread.daemon = True
        thread.start()

        return jsonify({'success': True, 'message': 'Benchmark started'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/benchmark/stop', methods=['POST'])
def stop_benchmark():
    global benchmark_process, benchmark_running
    try:
        if benchmark_process and benchmark_running:
            benchmark_process.terminate()
            time.sleep(1)
            if benchmark_process.poll() is None:
                benchmark_process.kill()
            benchmark_running = False
        return jsonify({'success': True, 'message': 'Benchmark stopped'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/benchmark/status', methods=['GET'])
def get_benchmark_status():
    return jsonify({'success': True, 'data': {'running': benchmark_running, 'timestamp': datetime.now().isoformat()}})


@app.route('/api/results', methods=['GET'])
def get_results():
    try:
        results = []
        if RESULTS_DIR.exists():
            for result_dir in RESULTS_DIR.iterdir():
                if result_dir.is_dir():
                    result_info = {'name': result_dir.name, 'created': datetime.fromtimestamp(
                        result_dir.stat().st_mtime).isoformat(), 'files': []}
                    for file in result_dir.rglob('*'):
                        if file.is_file():
                            result_info['files'].append({'name': file.name, 'path': str(
                                file.relative_to(RESULTS_DIR)), 'size': file.stat().st_size})
                    results.append(result_info)
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/logs', methods=['GET'])
def get_logs():
    try:
        logs = []
        if LOGS_DIR.exists():
            for log_file in sorted(LOGS_DIR.glob('*.log'), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
                logs.append({'name': log_file.name, 'created': datetime.fromtimestamp(
                    log_file.stat().st_mtime).isoformat(), 'size': log_file.stat().st_size})
        return jsonify({'success': True, 'data': logs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/logs/<log_name>', methods=['GET'])
def get_log_content(log_name):
    try:
        log_file = LOGS_DIR / log_name
        if not log_file.exists():
            return jsonify({'success': False, 'error': 'Log file not found'}), 404
        with open(log_file, 'r') as f:
            lines = f.readlines()
            content = ''.join(lines[-1000:])
        return jsonify({'success': True, 'data': content})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@socketio.on('connect')
def on_connect():
    emit('response', {'data': 'Already connected'})


@socketio.on('join_session')
def on_join_session(data):
    session_id = data.get('session_id', 'default')
    join_room(session_id)
    emit('response', {'data': f'Already joined {session_id}'})


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000,
                 debug=True, allow_unsafe_werkzeug=True)
