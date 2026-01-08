#!/usr/bin/env python3
"""GRAID Benchmark Web GUI - Flask Backend"""

from flask import Flask, request, jsonify, send_file, send_from_directory, render_template
from flask_cors import CORS
from flask_socketio import SocketIO, emit, join_room
import subprocess
import json
import os
import shutil
import base64
import threading
import time
from datetime import datetime
from pathlib import Path
import psutil
import tarfile
import re
import shlex
import csv
import selectors

WORKLOAD_MAP = {
    '00-randread': '4k Random Read',
    '01-seqread': '1M Sequential Read',
    '02-seqwrite': '1M Sequential Write',
    '09-randwrite': '4k Random Write'
}

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

            # Open log file for writing
            with open(log_file, 'w') as log:
                self.process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                    cwd=str(SCRIPT_DIR), env=env, text=True, bufsize=1
                )
                benchmark_process = self.process
                
                current_base_label = "Initializing..."

                # Use selectors for non-blocking I/O
                sel = selectors.DefaultSelector()
                sel.register(self.process.stdout, selectors.EVENT_READ)

                while True:
                    # Check for new data with a timeout
                    events = sel.select(timeout=0.5)
                    line = None
                    if events:
                        for key, mask in events:
                            line = key.fileobj.readline()
                    
                    if line:
                        # Write to log file
                        log.write(line)
                        log.flush() # Ensure it's written immediately
                        
                        # Debug: print to docker logs
                        print(f"BENCH_LOG: {line.strip()}", flush=True)

                            
                        # Parse status markers
                        msg = line.strip()

                        # Detect STATUS: STATE:
                        if "STATUS: STATE:" in msg:
                             try:
                                 state = msg.split("STATUS: STATE:")[1].strip()
                                 print(f"DETECTED STATE: {state}", flush=True)
                                 socketio.emit('run_status_update', {
                                    'status': state,
                                    'timestamp': datetime.now().isoformat()
                                 }, room=session_id)
                             except Exception as e:
                                 print(f"Error parsing state: {e}", flush=True)

                        if "STATUS: STAGE_PD_START" in msg:
                             print("DETECTED STAGE PD START", flush=True)
                             current_base_label = 'Baseline Performance Test\n'
                             socketio.emit('status_update', {
                                'stage': 'PD',
                                'label': current_base_label,
                                'timestamp': datetime.now().isoformat()
                            }, room=session_id)
                        elif "STATUS: STAGE_VD_START" in msg:
                             print("DETECTED STAGE VD START", flush=True)
                             current_base_label = 'RAID Performance Test\n'
                             socketio.emit('status_update', {
                                'stage': 'VD',
                                'label': current_base_label,
                                'timestamp': datetime.now().isoformat()
                            }, room=session_id)
                        elif "STATUS: WORKLOAD:" in msg:
                            # Format: STATUS: WORKLOAD: 00-randread-graid
                            try:
                                filename = msg.split("STATUS: WORKLOAD:")[1].strip()
                                friendly_name = filename
                                for key, val in WORKLOAD_MAP.items():
                                    if key in filename:
                                        friendly_name = val
                                        break
                                
                                new_label = f"{current_base_label} - {friendly_name}"
                                print(f"DETECTED WORKLOAD: {filename} -> {new_label}", flush=True)
                                
                                # Determine stage code based on label
                                stage_code = 'PD' if 'Baseline' in current_base_label else 'VD'
                                
                                socketio.emit('status_update', {
                                    'stage': stage_code,
                                    'label': new_label,
                                    'timestamp': datetime.now().isoformat()
                                }, room=session_id)
                            except Exception as e:
                                print(f"Error parsing workload: {e}", flush=True)
                    else:
                        # No data or EOF
                        if self.process.poll() is not None:
                             # Process ended
                             break
                
                # Wait for completion
                self.process.wait()
                print(f"BENCH_PROCESS_EXIT: rc={self.process.returncode}", flush=True)


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
                stdout = result.stdout.strip()
                # Find the start of the JSON object
                start_idx = stdout.find('{')
                if start_idx != -1:
                    nvme_info = json.loads(stdout[start_idx:]).get('Result', [])
        except Exception as e:
            print(f"Error getting graidctl nd info: {e}")

        # Get Controller info via graidctl
        controller_info = []
        try:
            result = subprocess.run(['graidctl', 'ls', 'cx', '--format', 'json'], capture_output=True, text=True)
            if result.returncode == 0:
                stdout = result.stdout.strip()
                # Find the start of the JSON object
                start_idx = stdout.find('{')
                if start_idx != -1:
                    controller_info = json.loads(stdout[start_idx:]).get('Result', [])
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


@app.route('/api/benchmark/trigger_snapshot', methods=['POST'])
def trigger_snapshot():
    try:
        if not benchmark_running:
            print("Snapshot trigger ignored: Benchmark is not running", flush=True)
            return jsonify({'success': True, 'message': 'Snapshot ignored: Benchmark stopped'})

        data = request.json
        test_name = data.get('test_name', 'unknown_test')
        output_dir = data.get('output_dir', '')
        
        # Emit event to frontend to take snapshot
        print(f"Triggering snapshot for {test_name}", flush=True)
        socketio.emit('snapshot_request', {
            'test_name': test_name,
            'output_dir': output_dir
        })
        
        return jsonify({'success': True, 'message': 'Snapshot requested'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/benchmark/save_snapshot', methods=['POST'])
def save_snapshot():
    try:
        data = request.json
        image_data = data.get('image')
        test_name = data.get('test_name')
        output_dir = data.get('output_dir') # Relative path from results dir

        if not image_data or not test_name:
            return jsonify({'success': False, 'error': 'Missing data'}), 400

        # Decode base64 image
        if ',' in image_data:
            header, encoded = image_data.split(',', 1)
        else:
            encoded = image_data

        image_binary = base64.b64decode(encoded)

        # Determine save path
        if output_dir:
             if output_dir.startswith('./'):
                 output_dir = output_dir[2:]
             
             # Security check: ensure no '..' to escape results dir
             if '..' in output_dir:
                 return jsonify({'success': False, 'error': 'Invalid path'}), 400
                 
             save_dir = SCRIPT_DIR / output_dir / 'report_view'
        else:
             save_dir = RESULTS_DIR / 'report_view'
             
        save_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{test_name}_report_view.png"
        file_path = save_dir / filename
        
        with open(file_path, 'wb') as f:
            f.write(image_binary)
            
        print(f"Snapshot saved to {file_path}", flush=True)

        return jsonify({'success': True, 'message': 'Snapshot saved'})
    except Exception as e:
        print(f"Error saving snapshot: {e}", flush=True)
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
        
        # Check if it's a special model path in scripts dir
        # User requirement: ./script/<model name>-result/<model name>/
        model_result_path = SCRIPT_DIR / f"{result_name}-result" / result_name
        


        target_path = None
        if result_path.exists():
            target_path = result_path
        elif model_result_path.exists():
            target_path = model_result_path
            
        if not target_path:
            return jsonify({'success': False, 'error': 'Result not found'}), 404
            
        result_path = target_path

        csv_data = []
        
        # Helper to parse CSV
        def parse_csv(file_path):
            data = []
            with open(file_path, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    data.append(row)
            return data

        # Helper to deduce workload from row data
        def get_workload_name(row):
            workload = "Unknown"
            try:
                # Special Case: Baseline 128k Seq Read -> 1M Sequential Read
                # User Requirement: use *SingleTest*01-seqread* as baseline for comparison
                filename_col = row.get('filename', '')
                if 'SingleTest' in filename_col:
                    if '01-seqread' in filename_col:
                        return "1M Sequential Read"
                    elif '02-seqwrite' in filename_col:
                        return "1M Sequential Write"
                
                # Special Case: 4k Random Read/Write Mix(70/30)
                if 'randrw73' in filename_col:
                     return "4k Random Read/Write Mix(70/30)"

                # Parse BlockSize
                bs_str = row.get('BlockSize', '0')
                try:
                    bs_float = float(bs_str)
                except ValueError:
                    bs_float = 0.0
                
                size_label = ""
                if bs_float == 4.0:
                    size_label = "4k"
                elif bs_float == 1024.0:
                    size_label = "1M"
                else:
                    # Fallback or other sizes
                    size_label = f"{bs_str}"

                # Parse Type
                # randread => Random Read 
                # read => Sequential Read 
                # randwrite => Random Write
                # write => Sequential Write
                row_type = row.get('Type', '').lower()
                type_label = ""
                
                if row_type == 'randread':
                    type_label = "Random Read"
                elif row_type == 'read':
                    type_label = "Sequential Read"
                elif row_type == 'randwrite':
                    type_label = "Random Write"
                elif row_type == 'write':
                    type_label = "Sequential Write"
                else:
                    type_label = row_type # Fallback
                
                if size_label and type_label:
                    workload = f"{size_label} {type_label}"
                
            except Exception as e:
                print(f"Error parsing workload: {e}")
            
            return workload

        if result_path.is_dir():
            # Search for CSV files recursively
            csv_files = list(result_path.rglob('*.csv'))

            # Filter based on type param if present
            req_type = request.args.get('type')
            
            filtered_files = []
            if req_type == 'baseline':
                filtered_files = [f for f in csv_files if '/PD/' in str(f) or '/pd/' in str(f)]
            elif req_type == 'graid':
                filtered_files = [f for f in csv_files if '/VD/' in str(f) or '/vd/' in str(f)]
            
            # If explicit filter yielded nothing, or no filter, use all found (maybe filter for test results)
            if not filtered_files:
                 # If we had a type but found nothing, maybe fallback? or return empty?
                 # If user specified baseline but no PD found, likely no PD data.
                 # But let's be safe and fallback to all if no specific filter matches (only if type not specified?)
                 if not req_type:
                    filtered_files = csv_files
                 # If req_type was set but empty, we return empty list essentially
            
            # Further filter for fio/diskspd files to avoid random csvs
            target_csvs = [f for f in filtered_files if 'fio-test' in f.name or 'diskspd-test' in f.name]
             
            # If no target csvs found, but we have filtered files, take them
            if not target_csvs and filtered_files:
                target_csvs = filtered_files
            
            # Parse all target CSVs and aggregate
            if target_csvs:
                for csv_file in target_csvs:
                    try:
                        file_data = parse_csv(csv_file)
                        
                        # Add workload to each row
                        for row in file_data:
                            row['Workload'] = get_workload_name(row)
                            
                        # Optional: Add source file info if needed, but schema might need to match
                        csv_data.extend(file_data)
                    except Exception as e:
                        print(f"Error parsing {csv_file}: {e}")
            else:
                 return jsonify({'success': False, 'error': 'No CSV data found'}), 404

        elif result_path.is_file() and result_path.name.endswith('.tar'):
            # Handle tar file
            import tarfile
            with tarfile.open(result_path, 'r') as tar:
                # Find Summary CSV in tar
                # Pattern: Look for *result/fio-test-r-*.csv
                summary_csv_member = None
                for member in tar.getmembers():
                    if 'result/fio-test-r-' in member.name and member.name.endswith('.csv'):
                        summary_csv_member = member
                        break
                
                if summary_csv_member:
                    # Parse summary CSV
                    f = tar.extractfile(summary_csv_member)
                    content = f.read().decode('utf-8')
                    reader = csv.DictReader(content.splitlines())
                    
                    req_type = request.args.get('type')
                    
                    for row in reader:
                        filename_col = row.get('filename', '')
                        
                        # Filtering Logic
                        # Baseline -> SingleTest
                        # Graid -> RAID
                        if req_type == 'baseline':
                            if 'SingleTest' not in filename_col:
                                continue
                        elif req_type == 'graid':
                            if 'RAID' not in filename_col:
                                continue
                        
                        row['Workload'] = get_workload_name(row)
                        csv_data.append(row)

                else:
                    # Fallback to old behavior: Find any CSV (maybe individual results?)
                    # Scan for all CSVs if summary not found?
                    # For now, let's just stick to the requested behavior or error out if critical?
                    # But better to support fallback if summary is missing but individual files exist.
                    
                    for member in tar.getmembers():
                         if member.name.endswith('.csv') and ('fio-test' in member.name or 'diskspd-test' in member.name):
                                # Extract and check type
                                # This is harder because we need to parse many files.
                                # Let's just try to find *any* csv for now as fallback
                                f = tar.extractfile(member)
                                # ... (simple valid csv check)
                                content = f.read().decode('utf-8')
                                reader = csv.DictReader(content.splitlines())
                                for row in reader:
                                    # Very basic fallback, likely won't match the filtering needs perfectly without duplicate logic
                                    # But given user request, the summary file SHOULD exist.
                                    row['Workload'] = get_workload_name(row)
                                    csv_data.append(row)

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
    socketio.run(app, host='0.0.0.0', port=50071,
                 debug=True, allow_unsafe_werkzeug=True)

