#!/usr/bin/env python3
"""GRAID Benchmark Web GUI - Flask Backend"""

from flask import Flask, request, jsonify, send_file, send_from_directory, render_template
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
import csv

app = Flask(__name__, static_folder='static', template_folder='templates')
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
giostat_process = None
giostat_thread = None
stop_giostat_event = threading.Event()

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
            
            # Start giostat monitoring
            start_giostat_monitoring(session_id)

            # Convert JSON config to Bash format
            target_config = SCRIPT_DIR / "graid-bench.conf"
            with open(target_config, 'w') as f:
                for key, value in config.items():
                    if isinstance(value, bool):
                        val_str = "true" if value else "false"
                        f.write(f'{key}="{val_str}"\n')
                    elif isinstance(value, list):
                        # Bash array: ("item1" "item2")
                        val_str = "(" + " ".join(f'"{v}"' for v in value) + ")"
                        f.write(f'{key}={val_str}\n')
                    else:
                        f.write(f'{key}="{value}"\n')
            
            socketio.emit('status', {
                'status': 'started',
                'message': 'Benchmark started',
                'timestamp': datetime.now().isoformat()
            }, room=session_id)

            log_file = LOGS_DIR / f"benchmark_{int(time.time())}.log"
            cmd = ['bash', str(SCRIPT_DIR / 'graid-bench.sh')]

            # Use venv environment
            env = os.environ.copy()
            venv_bin = BASE_DIR / 'venv' / 'bin'
            env['PATH'] = str(venv_bin) + os.pathsep + env['PATH']

            with open(log_file, 'w') as log:
                self.process = subprocess.Popen(
                    cmd, stdout=log, stderr=subprocess.STDOUT, cwd=str(SCRIPT_DIR), env=env
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
            stop_giostat_monitoring()


benchmark_manager = BenchmarkManager()

def start_giostat_monitoring(session_id):
    global giostat_thread, stop_giostat_event
    stop_giostat_event.clear()
    giostat_thread = threading.Thread(target=monitor_giostat, args=(session_id,))
    giostat_thread.daemon = True
    giostat_thread.start()

def stop_giostat_monitoring():
    global stop_giostat_event
    stop_giostat_event.set()

def monitor_giostat(session_id):
    global giostat_process
    try:
        # Run giostat -xmcd 1
        cmd = ['giostat', '-xmcd', '1']
        giostat_process = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        
        while not stop_giostat_event.is_set() and giostat_process.poll() is None:
            line = giostat_process.stdout.readline()
            if line:
                # Parse giostat output if needed, or just send raw line
                # For simplicity, we send the raw line and let frontend parse or display
                socketio.emit('giostat_data', {'line': line}, room=session_id)
            else:
                time.sleep(0.1)
                
    except Exception as e:
        print(f"Error in giostat monitoring: {e}")
    finally:
        if giostat_process:
            giostat_process.terminate()
            try:
                giostat_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                giostat_process.kill()

# API Routes

@app.route('/')
def index():
    return render_template('index.html')

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
        
        # Get NVMe info via graidctl
        nvme_info = []
        try:
            result = subprocess.run(['graidctl', 'ls', 'nd', '--format', 'json'], capture_output=True, text=True)
            if result.returncode == 0:
                nvme_info = json.loads(result.stdout).get('Result', [])
        except Exception as e:
            print(f"Error getting graidctl nd info: {e}")

        # Get Controller info via graidctl
        controller_info = []
        try:
            result = subprocess.run(['graidctl', 'ls', 'cx', '--format', 'json'], capture_output=True, text=True)
            if result.returncode == 0:
                controller_info = json.loads(result.stdout).get('Result', [])
        except Exception as e:
            print(f"Error getting graidctl cx info: {e}")

        return jsonify({
            'success': True,
            'data': {
                'cpu_cores': cpu_count,
                'cpu_freq': cpu_freq.current if cpu_freq else None,
                'memory_gb': memory.total / (1024**3),
                'memory_available_gb': memory.available / (1024**3),
                'nvme_info': nvme_info,
                'controller_info': controller_info
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
            stop_giostat_monitoring()
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
            for result_item in RESULTS_DIR.iterdir():
                # Handle both directories and tar files
                if result_item.is_file() and result_item.name.endswith('.tar'):
                     results.append({'name': result_item.name, 'type': 'archive', 'created': datetime.fromtimestamp(result_item.stat().st_mtime).isoformat(), 'size': result_item.stat().st_size})
                elif result_item.is_dir():
                    result_info = {'name': result_item.name, 'type': 'folder', 'created': datetime.fromtimestamp(
                        result_item.stat().st_mtime).isoformat(), 'files': []}
                    for file in result_item.rglob('*'):
                        if file.is_file():
                            result_info['files'].append({'name': file.name, 'path': str(
                                file.relative_to(RESULTS_DIR)), 'size': file.stat().st_size})
                    results.append(result_info)
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/results/<path:filename>', methods=['GET'])
def get_result_file(filename):
    try:
        return send_from_directory(RESULTS_DIR, filename)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 404

@app.route('/api/results/<result_name>/data', methods=['GET'])
def get_result_data(result_name):
    try:
        result_path = RESULTS_DIR / result_name
        if not result_path.exists():
            return jsonify({'success': False, 'error': 'Result not found'}), 404

        csv_data = []
        
        # Helper to parse CSV
        def parse_csv(file_path):
            data = []
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    data.append(row)
            return data

        if result_path.is_dir():
            # Search for CSV files
            # Priority: Look for files with 'fio-test' or 'diskspd-test' in name
            csv_files = list(result_path.rglob('*.csv'))
            target_csv = None
            
            # Simple heuristic to find the summary CSV
            for csv_file in csv_files:
                if 'fio-test' in csv_file.name or 'diskspd-test' in csv_file.name:
                    target_csv = csv_file
                    break
            
            if not target_csv and csv_files:
                target_csv = csv_files[0]
            
            if target_csv:
                csv_data = parse_csv(target_csv)
            else:
                return jsonify({'success': False, 'error': 'No CSV data found'}), 404

        elif result_path.is_file() and result_path.name.endswith('.tar'):
            # Handle tar file
            import tarfile
            with tarfile.open(result_path, 'r') as tar:
                # Find CSV in tar
                csv_member = None
                for member in tar.getmembers():
                    if member.name.endswith('.csv') and ('fio-test' in member.name or 'diskspd-test' in member.name):
                        csv_member = member
                        break
                
                if not csv_member:
                     # Fallback to any csv
                    for member in tar.getmembers():
                        if member.name.endswith('.csv'):
                            csv_member = member
                            break
                
                if csv_member:
                    f = tar.extractfile(csv_member)
                    content = f.read().decode('utf-8')
                    reader = csv.DictReader(content.splitlines())
                    for row in reader:
                        csv_data.append(row)
                else:
                     return jsonify({'success': False, 'error': 'No CSV data found in archive'}), 404

        return jsonify({'success': True, 'data': csv_data})
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
