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
import paramiko
from scp import SCPClient

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
CACHE_DIR = RESULTS_DIR / ".cache"

RESULTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)

benchmark_process = None
benchmark_running = False
giostat_process = None
giostat_thread = None
stop_giostat_event = threading.Event()

REMOTE_BASE_DIR = Path("/tmp/graid-gui")
ACTIVE_STATE_FILE = LOGS_DIR / "active_benchmark.json"

class BenchmarkState:
    @staticmethod
    def save(state):
        try:
            # Defensive mkdir
            LOGS_DIR.mkdir(exist_ok=True)
            print(f"DEBUG: Saving state to {ACTIVE_STATE_FILE}", flush=True)
            print(f"DEBUG: LOGS_DIR exists: {LOGS_DIR.exists()}, is_dir: {LOGS_DIR.is_dir()}", flush=True)
            with open(ACTIVE_STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            print(f"DEBUG: Error saving benchmark state: {e}", flush=True)
            # Try to see what's in /app/
            try:
                print(f"DEBUG: /app contents: {os.listdir('/app')}", flush=True)
                if os.path.exists('/app/logs'):
                    print(f"DEBUG: /app/logs contents: {os.listdir('/app/logs')}", flush=True)
            except: pass

    @staticmethod
    def load():
        try:
            if ACTIVE_STATE_FILE.exists():
                with open(ACTIVE_STATE_FILE, 'r') as f:
                    return json.load(f)
        except Exception as e:
            print(f"Error loading benchmark state: {e}")
        return None

    @staticmethod
    def clear():
        try:
            if ACTIVE_STATE_FILE.exists():
                ACTIVE_STATE_FILE.unlink()
        except Exception as e:
            print(f"Error clearing benchmark state: {e}")

# ANSI Escape sequence regex for stripping terminal colors
ANSI_ESCAPE = re.compile(r'(?:\x1B[@-_][0-?]*[ -/]*[@-~])')

def strip_ansi(text):
    if not text:
        return text
    return ANSI_ESCAPE.sub('', text)

class RemoteExecutor:
    """Handles command execution locally or remotely via SSH."""
    _lock = threading.Lock()

    def __init__(self, config=None):
        self.config = config or {}
        self.is_remote = self.config.get('REMOTE_MODE', False)
        self.ssh = None
        self.is_root = False
        self.has_sudo = False
        self.need_sudo_password = False
        
    def _get_ssh_client(self):
        with RemoteExecutor._lock:
            if self.ssh:
                try:
                    transport = self.ssh.get_transport()
                    if transport and transport.is_active():
                        return self.ssh
                except Exception:
                    pass
                # Connection dead, clean up
                try: self.ssh.close()
                except: pass
                self.ssh = None
            
            hostname = self.config.get('DUT_IP')
            if not hostname:
                raise ValueError("Remote mode enabled but DUT IP Address is missing in configuration.")
                
            username = self.config.get('DUT_USER', 'root')
            password = self.config.get('DUT_PASSWORD')
            port = int(self.config.get('DUT_PORT', 22))
            
            print(f"DEBUG: Connecting to remote DUT {hostname} as {username}...", flush=True)
            try:
                self.ssh = paramiko.SSHClient()
                self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                self.ssh.connect(hostname, port=port, username=username, password=password, timeout=10)
                
                # Check permissions
                self.is_root = False
                self.has_sudo = False
                self.need_sudo_password = False
                
                _, stdout, _ = self.ssh.exec_command('id -u')
                uid = stdout.read().decode().strip()
                if uid == '0':
                    self.is_root = True
                else:
                    # 1. Try passwordless sudo first
                    print(f"DEBUG: Checking passwordless sudo for {username}...", flush=True)
                    stdin, stdout, stderr = self.ssh.exec_command('sudo -n id -u')
                    if stdout.channel.recv_exit_status() == 0:
                        sudo_uid = stdout.read().decode().strip()
                        if sudo_uid == '0':
                            self.has_sudo = True
                    
                    # 2. If passwordless fails, try sudo with password if we have one
                    if not self.has_sudo and password:
                        print(f"DEBUG: Passwordless sudo failed, trying with password for {username}...", flush=True)
                        # Using sudo -S to read password from stdin
                        stdin, stdout, stderr = self.ssh.exec_command('sudo -S id -u')
                        stdin.write(password + '\n')
                        stdin.flush()
                        if stdout.channel.recv_exit_status() == 0:
                            sudo_uid = stdout.read().decode().strip()
                            if sudo_uid == '0':
                                self.has_sudo = True
                                self.need_sudo_password = True
                                print(f"DEBUG: Sudo with password verified for {username}", flush=True)
                    
                    if not self.has_sudo:
                        self.ssh.close()
                        self.ssh = None
                        raise PermissionError(f"User '{username}' does not have root privileges or sudo access on {hostname}. Hardware control requires root access.")
                
                return self.ssh
            except Exception as e:
                if self.ssh:
                    try: self.ssh.close()
                    except: pass
                self.ssh = None
                print(f"DEBUG: SSH Connection or Permission check failed: {e}", flush=True)
                raise ConnectionError(f"Failed to connect or verify permissions on remote DUT {hostname}: {str(e)}")

    def _to_remote_path(self, path):
        if not self.is_remote:
            return path
        # Map local absolute path to remote /tmp/graid-gui based path
        path_obj = Path(path).resolve()
        base_obj = BASE_DIR.resolve()
        
        if path_obj.is_absolute():
            # If it's under our BASE_DIR, relative it
            try:
                rel = path_obj.relative_to(base_obj)
                res = str(REMOTE_BASE_DIR / rel)
                # print(f"DEBUG: Mapped {path} -> {res} (rel: {rel})", flush=True)
                return res
            except ValueError:
                # Fallback: if it starts with /app/ we can manually relative it
                path_str = str(path_obj)
                base_str = str(base_obj)
                if path_str.startswith(base_str):
                    rel = path_str[len(base_str):].lstrip('/')
                    res = str(REMOTE_BASE_DIR / rel)
                    return res
                return str(path)
        return str(path)

    def run(self, cmd, cwd=None, env=None, capture_output=True, text=True):
        if not self.is_remote:
            return subprocess.run(cmd, cwd=cwd, env=env, capture_output=capture_output, text=text)
        
        ssh = self._get_ssh_client()
        password = self.config.get('DUT_PASSWORD')
        
        # Prepare environment variables string (Paramiko's environment param is often disabled on servers)
        env_vars = ""
        if env:
            for k, v in env.items():
                env_vars += f"export {k}={shlex.quote(str(v))} && "
        
        # Prepare command
        actual_cmd = list(cmd)
        target_cmd = []
        if not self.is_root and self.has_sudo:
            if self.need_sudo_password:
                target_cmd = ['sudo', '-S'] + actual_cmd
            else:
                target_cmd = ['sudo', '-n'] + actual_cmd
        else:
            target_cmd = actual_cmd
            
        cmd_str = " ".join(shlex.quote(str(c)) for c in target_cmd)
        if cwd:
            remote_cwd = self._to_remote_path(cwd)
            cmd_str = f"cd {shlex.quote(str(remote_cwd))} && {cmd_str}"
        
        full_cmd = f"{env_vars}{cmd_str}"
            
        stdin, stdout, stderr = ssh.exec_command(full_cmd)
        
        if self.need_sudo_password and password:
            stdin.write(password + '\n')
            stdin.flush()
            
        exit_status = stdout.channel.recv_exit_status()
        
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=exit_status,
            stdout=stdout.read().decode('utf-8') if text else stdout.read(),
            stderr=stderr.read().decode('utf-8') if text else stderr.read()
        )

    def Popen(self, cmd, cwd=None, env=None, **kwargs):
        if not self.is_remote:
            return subprocess.Popen(cmd, cwd=cwd, env=env, **kwargs)
        
        ssh = self._get_ssh_client()
        password = self.config.get('DUT_PASSWORD')
        
        # Prepare command
        actual_cmd = list(cmd)
        target_cmd = []
        if not self.is_root and self.has_sudo:
            if self.need_sudo_password:
                target_cmd = ['sudo', '-S'] + actual_cmd
            else:
                target_cmd = ['sudo', '-n'] + actual_cmd
        else:
            target_cmd = actual_cmd
            
        # Prepare final command string
        actual_binary_cmd = " ".join(shlex.quote(str(c)) for c in target_cmd)
        
        setup_parts = []
        if env:
            for k, v in env.items():
                setup_parts.append(f"export {k}={shlex.quote(str(v))}")
        if cwd:
            remote_cwd = self._to_remote_path(cwd)
            setup_parts.append(f"cd {shlex.quote(str(remote_cwd))}")
            
        setup_str = " && ".join(setup_parts)
        if setup_str:
            wrapped_cmd = f"echo $$ && {setup_str} && exec {actual_binary_cmd}"
        else:
            wrapped_cmd = f"echo $$ && exec {actual_binary_cmd}"
        
        # Paramiko recv_ready is more reliable for streaming
        stdin, stdout, stderr = ssh.exec_command(wrapped_cmd, get_pty=True)
        
        if self.need_sudo_password and password:
            stdin.write(password + '\n')
            stdin.flush()
            
        # Read the first line which should be our PID
        try:
            line = stdout.readline()
            remote_pid = line.strip()
            print(f"DEBUG: Remote process started with PID: {remote_pid}", flush=True)
        except Exception as e:
            print(f"DEBUG: Failed to read remote PID: {e}", flush=True)
            remote_pid = None

        class RemoteProcess:
            def __init__(self, stdin, stdout, stderr, pid, executor):
                self.stdin = stdin
                self.stdout = stdout
                self.stderr = stderr
                self.pid = pid
                self.executor = executor
                self.returncode = None
                self._buffer = ""

            def poll(self):
                if self.stdout.channel.exit_status_ready():
                    self.returncode = self.stdout.channel.recv_exit_status()
                    return self.returncode
                return None

            def wait(self, timeout=None):
                # Ensure we consume all remaining output
                # This is critical because paramiko might have buffered data even if exit status is ready
                self.returncode = self.stdout.channel.recv_exit_status()
                return self.returncode

            def terminate(self):
                if self.pid:
                    print(f"DEBUG: Terminating remote process group {self.pid}...", flush=True)
                    # We kill the process group (using negative PID) to ensure all children are killed
                    self.executor.run(['kill', '-TERM', f'-{self.pid}'])
                self.stdout.channel.close()

            def kill(self):
                if self.pid:
                    print(f"DEBUG: Killing remote process group {self.pid}...", flush=True)
                    self.executor.run(['kill', '-9', f'-{self.pid}'])
                self.stdout.channel.close()

        return RemoteProcess(stdin, stdout, stderr, remote_pid, self)

    def check_dependencies(self):
        if not self.is_remote:
            # Local mode dependencies are assumed to be managed by the container
            return {"success": True, "dependencies": {}}
            
        deps = ['fio', 'jq', 'nvme', 'bc', 'python3', 'graidctl']
        results = {}
        for dep in deps:
            res = self.run(['which', dep], capture_output=True)
            results[dep] = res.returncode == 0
        
        # Check pandas
        res = self.run(['python3', '-c', 'import pandas; print(True)'], capture_output=True)
        results['pandas'] = res.returncode == 0
        
        return results

    def sync_to_remote(self, local_path, remote_path):
        if not self.is_remote:
            return
        ssh = self._get_ssh_client()
        remote_path_mapped = self._to_remote_path(remote_path)
        
        # Ensure remote parent directory exists
        parent = str(Path(remote_path_mapped).parent)
        self.run(['mkdir', '-p', parent])
        
        transport = ssh.get_transport()
        if not transport:
             raise ConnectionError("SSH transport is not available for SCP")
        with SCPClient(transport) as scp:
            scp.put(local_path, remote_path_mapped, recursive=True)

    def sync_from_remote(self, local_path, remote_path):
        if not self.is_remote:
            return
        ssh = self._get_ssh_client()
        remote_path_mapped = self._to_remote_path(remote_path)
        print(f"DEBUG: sync_from_remote: {remote_path} -> {remote_path_mapped} (local: {local_path})", flush=True)
        
        # Check if remote path exists before getting
        res = self.run(['ls', '-d', remote_path_mapped], capture_output=True)
        if res.returncode != 0:
            print(f"DEBUG: Remote path {remote_path_mapped} does not exist, skipping sync_from_remote", flush=True)
            return

        # Ensure local directory exists
        Path(local_path).mkdir(parents=True, exist_ok=True)

        transport = ssh.get_transport()
        if not transport:
             raise ConnectionError("SSH transport is not available for SCP")
        try:
            with SCPClient(transport) as scp:
                scp.get(remote_path_mapped, local_path, recursive=True)
        except Exception as e:
            print(f"DEBUG: SCP get failed: {e}", flush=True)

    def __del__(self):
        if self.ssh:
            self.ssh.close()

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
        self.current_log_file = None
        self.latest_progress = {
            'percentage': 0,
            'elapsed': 0,
            'current_step': 0,
            'total_steps': 0
        }
        self.current_stage_info = {
            'stage': '',
            'label': ''
        }

    def recover_state(self, state):
        global benchmark_running
        try:
            self.current_log_file = Path(state['log_file'])
            session_id = state['session_id']
            config = state['config']
            start_time = state['start_time']
            
            start_time = state['start_time']
            # Restore stage info if available
            self.current_stage_info = state.get('stage_info', {'stage': '', 'label': ''})
            
            executor = RemoteExecutor(config)
            
            # Check if remote process is alive
            # Looking for 'graid-bench.sh' or 'bench.sh' on remote
            res = executor.run(['pgrep', '-f', 'graid-bench.sh'], capture_output=True, text=True)
            if res.returncode == 0:
                print(f"DEBUG: Recovering active benchmark on session {session_id}", flush=True)
                benchmark_running = True
                
                # Start a thread to wait for completion and sync
                thread = threading.Thread(
                    target=self._wait_for_completion,
                    args=(executor, session_id, config)
                )
                thread.daemon = True
                thread.start()

                # Restart giostat monitoring
                start_giostat_monitoring(session_id, executor)

                # Emit status to UI
                socketio.emit('status', {
                    'status': 'started',
                    'message': 'Benchmark is already running (Recovered)',
                    'timestamp': datetime.now().isoformat()
                }, room=session_id)
                
                return True
            else:
                print("DEBUG: Active state found but no remote benchmark process detected. Clearing state.")
                BenchmarkState.clear()
        except Exception as e:
            print(f"Error during state recovery: {e}")
        return False

    def _wait_for_completion(self, executor, session_id, config):
        global benchmark_running
        try:
            # Poll until pgrep fails
            while True:
                res = executor.run(['pgrep', '-f', 'graid-bench.sh'], capture_output=True, text=True)
                if res.returncode != 0:
                    break
                time.sleep(10)
            
            # Sync back
            if executor.is_remote:
                try:
                    executor.sync_from_remote(str(RESULTS_DIR.parent), str(RESULTS_DIR))
                    executor.sync_from_remote(str(LOGS_DIR.parent), str(LOGS_DIR))
                except Exception as e:
                    print(f"Error syncing back after recovery: {e}")
                    
            socketio.emit('status', {
                'status': 'completed',
                'message': 'Benchmark completed (recovered)',
                'timestamp': datetime.now().isoformat()
            }, room=session_id)
            
        finally:
            benchmark_running = False
            BenchmarkState.clear()
            stop_giostat_monitoring()

    def run_benchmark(self, config, session_id):
        global benchmark_running, benchmark_process
        try:
            ConfigManager.save_config(config)
            executor = RemoteExecutor(config)
            benchmark_running = True
            
            # Start giostat monitoring
            start_giostat_monitoring(session_id, executor)

            # Sync scripts to remote if in remote mode
            if executor.is_remote:
                socketio.emit('status', {
                    'status': 'syncing',
                    'message': 'Syncing scripts to remote DUT...',
                    'timestamp': datetime.now().isoformat()
                }, room=session_id)
                
                # Ensure remote directories exist and are writable
                remote_script_dir = executor._to_remote_path(str(SCRIPT_DIR))
                remote_results_dir = executor._to_remote_path(str(RESULTS_DIR))
                remote_logs_dir = executor._to_remote_path(str(LOGS_DIR))
                
                executor.run(['mkdir', '-p', remote_script_dir, remote_results_dir, remote_logs_dir])
                
                # If we are using sudo, make sure we own the directory or it's writable
                if not executor.is_root and executor.has_sudo:
                    executor.run(['sudo', 'chown', '-R', executor.config.get('DUT_USER', 'root'), 
                                 executor._to_remote_path(str(REMOTE_BASE_DIR))])
                
                executor.run(['rm', '-rf', remote_script_dir])
                executor.sync_to_remote(str(SCRIPT_DIR), str(SCRIPT_DIR.parent))
                
                # Debug: Verify remote file content
                checksum = executor.run(['md5sum', str(SCRIPT_DIR / 'graid-bench.sh')], capture_output=True, text=True)
                print(f"DEBUG: Remote script checksum: {checksum.stdout.strip()}", flush=True)

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
            
            # Sync generated config to remote
            if executor.is_remote:
                executor.sync_to_remote(str(target_config), str(target_config))

            socketio.emit('status', {
                'status': 'started',
                'message': 'Benchmark started',
                'timestamp': datetime.now().isoformat()
            }, room=session_id)

            self.latest_progress = {
                'percentage': 0,
                'elapsed': 0,
                'remaining': 0,
                'current_step': 0,
                'total_steps': 0
            }

            self.current_log_file = LOGS_DIR / f"benchmark_{int(time.time())}.log"
            log_file = self.current_log_file
            
            start_time = time.time()
            
            # Save active state for recovery
            BenchmarkState.save({
                'session_id': session_id,
                'log_file': str(log_file),
                'config': config,
                'start_time': start_time,
                'status': 'started'
            })

            script_path = SCRIPT_DIR / 'graid-bench.sh'
            if executor.is_remote:
                script_path = executor._to_remote_path(str(script_path))
                
            cmd = ['bash', str(script_path)]

            # Use venv environment
            env = os.environ.copy()
            venv_bin = BASE_DIR / 'venv' / 'bin' # This venv is local?
            # If remote, we might need to adjust PATH differently or assume standard env
            # But let's fix the script path first.
            
            if executor.is_remote:
                 # For remote, we don't necessarily have the same venv path unless we synced it?
                 # Assuming remote system has necessary python/tools in path or we rely on check_dependencies
                 pass 
            else:
                 env['PATH'] = str(venv_bin) + os.pathsep + env['PATH']

            # Get total estimated time
            total_est_seconds = 0
            try:
                est_cmd = ['bash', executor._to_remote_path(str(SCRIPT_DIR / 'est_time.sh'))]
                result = executor.run(est_cmd, cwd=str(SCRIPT_DIR), env=env)
                if result.returncode == 0:
                    # Parse "Estimated Completion Time: 00:00:15 (dd:hh:mm)"
                    match = re.search(r'Estimated Completion Time: (\d+):(\d+):(\d+)', result.stdout)
                    if match:
                        days, hours, minutes = map(int, match.groups())
                        total_est_seconds = days * 86400 + hours * 3600 + minutes * 60
                        print(f"DEBUG: Total estimated seconds: {total_est_seconds}", flush=True)
            except Exception as e:
                print(f"Error getting estimated time: {e}", flush=True)

            # Open log file for writing
            with open(log_file, 'w') as log:
                self.process = executor.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, 
                    cwd=str(SCRIPT_DIR), env=env, text=True, bufsize=1
                )
                benchmark_process = self.process
                
                current_base_label = "Initializing..."
                self.current_step = 0
                self.total_steps = 0
                self.last_error = None

                # Robust log reading
                while True:
                    line = self.process.stdout.readline()
                    if line:
                            # Write to log file
                            log.write(line)
                            log.flush()
                            
                            # Clean message for parsing
                            msg = strip_ansi(line.strip())
                            if not msg:
                                continue
                                
                            # Emit log line to frontend
                            if not any(x in msg for x in ["DEBUG:", "Emitting giostat", "snapshot_request"]):
                                 socketio.emit('bench_log', {'line': msg}, room=session_id)

                            # Debug: print to docker logs
                            print(f"BENCH_LOG: {msg}", flush=True)

                            # Detect STATUS markers
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

                            elif "STATUS: ERROR:" in msg:
                                 try:
                                     error_msg = msg.split("STATUS: ERROR:")[1].strip()
                                     print(f"DETECTED ERROR: {error_msg}", flush=True)
                                     self.last_error = error_msg
                                     # Optional: Emit error immediately if needed, but we usually wait for exit
                                 except Exception as e:
                                     print(f"Error parsing error message: {e}", flush=True)


                            elif "STATUS: STAGE_PD_START" in msg:
                                 print("DETECTED STAGE PD START", flush=True)
                                 current_base_label = 'Baseline Performance Test\n'
                                 self.current_stage_info = {'stage': 'PD', 'label': current_base_label}
                                 socketio.emit('status_update', {
                                    'stage': 'PD',
                                    'label': current_base_label,
                                    'timestamp': datetime.now().isoformat()
                                }, room=session_id)
                                 # Update persistent state
                                 BenchmarkState.save({
                                     'session_id': session_id,
                                     'log_file': str(self.current_log_file),
                                     'config': config,
                                     'start_time': start_time,
                                     'status': 'started',
                                     'stage_info': self.current_stage_info
                                 })

                            elif "STATUS: STAGE_VD_START" in msg:
                                 print("DETECTED STAGE VD START", flush=True)
                                 current_base_label = 'RAID Performance Test\n'
                                 self.current_stage_info = {'stage': 'VD', 'label': current_base_label}
                                 socketio.emit('status_update', {
                                    'stage': 'VD',
                                    'label': current_base_label,
                                    'timestamp': datetime.now().isoformat()
                                }, room=session_id)
                                 # Update persistent state
                                 BenchmarkState.save({
                                     'session_id': session_id,
                                     'log_file': str(self.current_log_file),
                                     'config': config,
                                     'start_time': start_time,
                                     'status': 'started',
                                     'stage_info': self.current_stage_info
                                 })

                            elif "STATUS: WORKLOAD:" in msg:
                                try:
                                    filename = msg.split("STATUS: WORKLOAD:")[1].strip()
                                    friendly_name = filename
                                    for key, val in WORKLOAD_MAP.items():
                                        if key in filename:
                                            friendly_name = val
                                            break
                                    
                                    new_label = f"{current_base_label} - {friendly_name}"
                                    print(f"DETECTED WORKLOAD: {filename} -> {new_label}", flush=True)
                                    stage_code = 'PD' if 'Baseline' in current_base_label else 'VD'
                                    
                                    self.current_stage_info = {'stage': stage_code, 'label': new_label}
                                    socketio.emit('status_update', {
                                        'stage': stage_code,
                                        'label': new_label,
                                        'timestamp': datetime.now().isoformat()
                                    }, room=session_id)
                                    # Update persistent state
                                    BenchmarkState.save({
                                        'session_id': session_id,
                                        'log_file': str(self.current_log_file),
                                        'config': config,
                                        'start_time': start_time,
                                        'status': 'started',
                                        'stage_info': self.current_stage_info
                                    })
                                except Exception as e:
                                    print(f"Error parsing workload: {e}", flush=True)

                            elif "STATUS: TOTAL_STEPS:" in msg:
                                try:
                                    self.total_steps = int(msg.split("STATUS: TOTAL_STEPS:")[1].strip())
                                    self.current_step = 0
                                    print(f"DEBUG: Global Total Steps set to {self.total_steps}", flush=True)
                                except: pass

                            elif "STATUS: SNAPSHOT:" in msg:
                                 try:
                                     # Format: STATUS: SNAPSHOT: test_name="name" output_dir="dir"
                                     test_match = re.search(r'test_name="([^"]+)"', msg)
                                     dir_match = re.search(r'output_dir="([^"]+)"', msg)
                                     
                                     tn = test_match.group(1) if test_match else "unknown"
                                     od = dir_match.group(1) if dir_match else ""
                                     
                                     print(f"TRIGGER SNAPSHOT -> test={tn}, dir={od}", flush=True)
                                     socketio.emit('snapshot_request', {
                                         'test_name': tn,
                                         'output_dir': od
                                     }, room=session_id)
                                 except Exception as e:
                                     print(f"Error parsing snapshot marker: {e}", flush=True)

                            elif "STATUS: TICK" in msg:
                                try:
                                    self.current_step += 1
                                    if self.total_steps > 0:
                                        percentage = (self.current_step / self.total_steps) * 100
                                        elapsed = int(time.time() - start_time)
                                    
                                    # Refined remaining time
                                    remaining = 0
                                    if percentage > 0:
                                        total_projected = elapsed / (percentage / 100)
                                        remaining = int(total_projected - elapsed)
                                    elif total_est_seconds > 0:
                                        remaining = total_est_seconds - elapsed
                                    
                                    if remaining < 0: remaining = 0
                                    
                                    self.latest_progress = {
                                        'current_step': self.current_step,
                                        'total_steps': self.total_steps,
                                        'percentage': round(percentage, 2),
                                        'elapsed': elapsed,
                                        'remaining': remaining,
                                        'timestamp': datetime.now().isoformat()
                                    }
                                    socketio.emit('progress_update', self.latest_progress, room=session_id)
                                    
                                    # Update persistent state with latest progress (every 10 ticks to reduce I/O)
                                    if self.current_step % 10 == 0:
                                        try:
                                            saved = BenchmarkState.load() or {}
                                            saved['progress'] = self.latest_progress
                                            BenchmarkState.save(saved)
                                        except:
                                            pass
                                except Exception as e:
                                    print(f"Error handling progress tick: {e}", flush=True)
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
                fail_msg = self.last_error if self.last_error else f'Failed: {self.process.returncode} (No error captured)'
                socketio.emit('status', {
                    'status': 'failed',
                    'message': fail_msg,
                    'timestamp': datetime.now().isoformat()
                }, room=session_id)
        except Exception as e:
            socketio.emit('error', {
                'message': str(e),
                'timestamp': datetime.now().isoformat()
            }, room=session_id)
        finally:
            if executor.is_remote:
                # Sync results and logs back from remote
                try:
                    executor.sync_from_remote(str(RESULTS_DIR.parent), str(RESULTS_DIR))
                    executor.sync_from_remote(str(LOGS_DIR.parent), str(LOGS_DIR))
                except Exception as e:
                    print(f"Error syncing back results: {e}", flush=True)

            benchmark_running = False
            stop_giostat_monitoring()


benchmark_manager = BenchmarkManager()

def start_giostat_monitoring(session_id, executor=None):
    global giostat_thread, stop_giostat_event
    stop_giostat_event.clear()
    giostat_thread = threading.Thread(target=monitor_giostat, args=(session_id, executor))
    giostat_thread.daemon = True
    giostat_thread.start()

def stop_giostat_monitoring():
    global stop_giostat_event
    stop_giostat_event.set()

def monitor_giostat(session_id, executor=None):
    global giostat_process
    
    # Open debug log file for giostat output
    debug_log_path = LOGS_DIR / "giostat_debug.log"
    MAX_LOG_SIZE = 10 * 1024 * 1024  # 10MB max log size
    
    try:
        if not executor:
            executor = RemoteExecutor(ConfigManager.load_config())
        
        # Check if log file exceeds 10MB, if so truncate it
        if debug_log_path.exists() and debug_log_path.stat().st_size > MAX_LOG_SIZE:
            debug_log_path.unlink()  # Delete and create fresh
        
        debug_log = open(debug_log_path, 'a')
        debug_log.write(f"\n--- giostat monitoring started at {datetime.now().isoformat()} ---\n")
        debug_log.flush()
            
        # Run giostat -xmcdz 5 (5 second interval, skip zero activity)
        cmd = ['giostat', '-xmcdz', '5']
        giostat_process = executor.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        
        headers = None
        header_map = {}

        while not stop_giostat_event.is_set() and giostat_process.poll() is None:
            line = giostat_process.stdout.readline()
            if not line:
                time.sleep(0.1)
                continue

            line = strip_ansi(line) # Clean ANSI colors (e.g., [32;22m)

            parts = line.strip().split()
            if not parts:
                continue

            # Check log size and rotate if needed
            try:
                if debug_log_path.stat().st_size > MAX_LOG_SIZE:
                    debug_log.close()
                    debug_log_path.unlink()
                    debug_log = open(debug_log_path, 'a')
                    debug_log.write(f"\n--- giostat log rotated at {datetime.now().isoformat()} ---\n")
            except:
                pass
            
            # Write raw line to debug log
            debug_log.write(f"{line}")
            debug_log.flush()
            
            # Robust header detection: Look for 'Device', 'DEV', 'NAME', or 'r/s'
            header_keywords = ['Device', 'DEV', 'NAME', 'Device:', 'r/s', 'rio/s', 'Device-Name']
            if any(k in parts for k in header_keywords) or any(k in line for k in ['rio/s', 'wio/s', 'rMB/s']):
                headers = parts
                header_map = {h.strip(':'): i for i, h in enumerate(headers)}
                debug_log.write(f"DEBUG: Detected giostat headers: {header_map}\n")
                continue

            # Fallback if we see device lines but haven't found a header yet
            if not headers:
                if parts[0].startswith('nvme') or parts[0].startswith('gdg') or parts[0].startswith('md'):
                    # Guessing standard iostat -x format: 
                    # Device r/s w/s rMB/s wMB/s ...
                    debug_log.write(f"DEBUG: No header detected yet, using fallback mapping for {parts[0]}\n")
                    headers = ['Device', 'r/s', 'w/s', 'rMB/s', 'wMB/s', 'r_await', 'w_await']
                    header_map = {h: i for i, h in enumerate(headers)}

            if headers and len(parts) >= len(headers):
                try:
                    dev_name = parts[header_map.get('Device', 0)].replace('/dev/', '')
                    
                    # Mapping based on common giostat columns
                    # r/s -> iops_read, rMB/s -> bw_read, r_await/await -> lat_read
                    # w/s -> iops_write, wMB/s -> bw_write, w_await/await -> lat_write
                    
                    # Different versions of giostat have different column names
                    def get_val(keys, default=0.0):
                        for k in keys:
                            if k in header_map:
                                try: return float(parts[header_map[k]])
                                except: pass
                        return default

                    data = {
                        'dev': dev_name,
                        'iops_read': get_val(['r/s', 'rio/s']),
                        'bw_read': get_val(['rMB/s', 'rkB/s']) / (1.0 if 'rMB/s' in header_map else 1024.0),
                        'lat_read': get_val(['r_await', 'await']),
                        'iops_write': get_val(['w/s', 'wio/s']),
                        'bw_write': get_val(['wMB/s', 'wkB/s']) / (1.0 if 'wMB/s' in header_map else 1024.0),
                        'lat_write': get_val(['w_await', 'await'])
                    }

                    # Only log active devices to debug file (not spamming for idle devices)
                    if data['iops_read'] > 0 or data['iops_write'] > 0:
                        debug_log.write(f"DEBUG: Emitting data for {dev_name}: IOPS R:{data['iops_read']:.0f} W:{data['iops_write']:.0f}\n")
                    
                    socketio.emit('giostat_data_v2', data, room=session_id)
                    # Also keep v1 for simple terminal display if needed
                    socketio.emit('giostat_data', {'line': line}, room=session_id)
                except Exception as e:
                    print(f"Error parsing giostat line: {e}")
                    socketio.emit('giostat_data', {'line': line}, room=session_id)
            else:
                # Fallback for raw lines
                socketio.emit('giostat_data', {'line': line}, room=session_id)
                
    except Exception as e:
        print(f"Error in giostat monitoring: {e}")
    finally:
        try:
            debug_log.write(f"--- giostat monitoring ended at {datetime.now().isoformat()} ---\n")
            debug_log.close()
        except:
            pass
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


@app.route('/api/system-info', methods=['GET', 'POST'])
def get_system_info():
    try:
        cpu_count = psutil.cpu_count(logical=False)
        cpu_freq = psutil.cpu_freq()
        memory = psutil.virtual_memory()
        
        config = None
        if request.method == 'POST':
            config = request.json.get('config')
            
        if not config:
            config = ConfigManager.load_config()
            
        executor = RemoteExecutor(config)
        
        # Get NVMe info via graidctl
        nvme_info = []
        try:
            result = executor.run(['graidctl', 'ls', 'nd', '--format', 'json'], capture_output=True, text=True)
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
            result = executor.run(['graidctl', 'ls', 'cx', '--format', 'json'], capture_output=True, text=True)
            if result.returncode == 0:
                stdout = result.stdout.strip()
                # Find the start of the JSON object
                start_idx = stdout.find('{')
                if start_idx != -1:
                    controller_info = json.loads(stdout[start_idx:]).get('Result', [])
        except Exception as e:
            print(f"Error getting graidctl cx info: {e}")

        # Get remote hostname
        hostname_dut = "Unknown"
        try:
            res = executor.run(['hostname'], capture_output=True, text=True)
            if res.returncode == 0:
                hostname_dut = res.stdout.strip()
        except: pass

        return jsonify({
            'success': True,
            'data': {
                'cpu_cores': cpu_count,
                'cpu_freq': cpu_freq.current if cpu_freq else None,
                'memory_gb': memory.total / (1024**3),
                'memory_available_gb': memory.available / (1024**3),
                'nvme_info': nvme_info,
                'controller_info': controller_info,
                'hostname': hostname_dut
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/license-info', methods=['GET', 'POST'])
def get_license_info():
    try:
        config = None
        if request.method == 'POST':
            config = request.json.get('config')
            
        if not config:
            config = ConfigManager.load_config()
            
        executor = RemoteExecutor(config)
        license_info = {}
        try:
            result = executor.run(['graidctl', 'desc', 'lic', '--format', 'json'], capture_output=True, text=True)
            if result.returncode == 0:
                stdout = result.stdout.strip()
                # Find the start of the JSON object
                start_idx = stdout.find('{')
                if start_idx != -1:
                    license_info = json.loads(stdout[start_idx:]).get('Result', {})
        except Exception as e:
            print(f"Error getting license info: {e}")

        return jsonify({'success': True, 'data': license_info})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/benchmark/test-connection', methods=['POST'])
def test_connection():
    try:
        data = request.json
        config = request.json.get('config')
        if not config:
            return jsonify({'success': False, 'error': 'No configuration provided'}), 400
            
        executor = RemoteExecutor(config)
        # Test basic connection and permission
        res = executor.run(['echo', 'success'], capture_output=True, text=True)
        if res.returncode == 0:
            # Also check dependencies
            dep_results = executor.check_dependencies()
            missing = [d for d, present in dep_results.items() if not present]
            
            msg = 'Connection established and permissions verified.'
            if missing:
                msg += f" However, some dependencies are missing: {', '.join(missing)}. Please run 'Setup DUT' to install them."
                
            return jsonify({
                'success': True, 
                'message': msg,
                'dependencies': dep_results
            })
        else:
            return jsonify({'success': False, 'error': f"Connection test failed: {res.stderr}"})
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/benchmark/setup-dut', methods=['POST'])
def setup_dut():
    try:
        config = request.json.get('config')
        if not config:
            return jsonify({'success': False, 'error': 'No configuration provided'}), 400
            
        executor = RemoteExecutor(config)
        if not executor.is_remote:
            return jsonify({'success': False, 'error': 'Target is local. No remote setup needed.'})

        # 1. Sync setup_env.sh to remote
        setup_script_path = os.path.join(os.path.dirname(__file__), 'scripts', 'setup_env.sh')
        if not os.path.exists(setup_script_path):
             return jsonify({'success': False, 'error': f'Setup script not found on host at {setup_script_path}.'})
             
        executor.run(['mkdir', '-p', '/tmp/graid-setup'])
        executor.sync_to_remote(setup_script_path, '/tmp/graid-setup/setup_env.sh')
        
        # 2. Run setup_env.sh --dut-mode
        # We use Popen-like behavior or just run with a long timeout
        res = executor.run(['bash', '/tmp/graid-setup/setup_env.sh', '--dut-mode'], capture_output=True, text=True)
        
        if res.returncode == 0:
            return jsonify({'success': True, 'message': 'Remote DUT environment setup successfully.', 'details': res.stdout})
        else:
            return jsonify({'success': False, 'error': f"Setup failed: {res.stderr}", 'details': res.stdout})

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


@app.route('/api/benchmark/logs', methods=['GET'])
def get_benchmark_logs():
    try:
        log_file = None
        # Try to get active log first from benchmark_manager
        if benchmark_manager.process and benchmark_manager.current_log_file:
            log_file = benchmark_manager.current_log_file
        
        # Fallback to latest log in directory sorted by modification time
        if not log_file and LOGS_DIR.exists():
            logs = sorted(LOGS_DIR.glob('benchmark_*.log'), key=lambda x: x.stat().st_mtime, reverse=True)
            if logs:
                log_file = logs[0]
        
        if log_file and log_file.exists():
            with open(log_file, 'r') as f:
                # Return last 100 lines to match typical tail -n 100 behavior
                lines = f.readlines()
                return jsonify({'success': True, 'logs': [l.strip() for l in lines[-100:]]})
        
        return jsonify({'success': True, 'logs': []})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def parse_graidctl_json(output):
    """Parses JSON from graidctl output, skipping the first checkmark line if present."""
    if not output:
        return {}
    lines = output.strip().split('\n')
    json_str = ""
    for line in lines:
        if line.strip().startswith('{'):
            json_str = '\n'.join(lines[lines.index(line):])
            break
    if not json_str:
        return {}
    return json.loads(json_str)


@app.route('/api/graid/check', methods=['GET', 'POST'])
def check_graid_resources():
    try:
        has_resources = False
        findings = []
        
        config = None
        if request.method == 'POST':
            config = request.json.get('config')
            
        if not config:
            config = ConfigManager.load_config()
            
        executor = RemoteExecutor(config)
        
        # Check VDs
        res = executor.run(['graidctl', 'ls', 'vd', '--format', 'json'], capture_output=True, text=True)
        if res.returncode == 0:
            vds = parse_graidctl_json(res.stdout).get('Result', [])
            if vds:
                has_resources = True
                findings.append(f"{len(vds)} VDs")
        
        # Check DGs
        res = executor.run(['graidctl', 'ls', 'dg', '--format', 'json'], capture_output=True, text=True)
        if res.returncode == 0:
            dgs = parse_graidctl_json(res.stdout).get('Result', [])
            if dgs:
                has_resources = True
                findings.append(f"{len(dgs)} DGs")

        # Check PDs
        res = executor.run(['graidctl', 'ls', 'pd', '--format', 'json'], capture_output=True, text=True)
        if res.returncode == 0:
            pds = parse_graidctl_json(res.stdout).get('Result', [])
            if pds:
                has_resources = True
                findings.append(f"{len(pds)} PDs")

        return jsonify({'success': True, 'has_resources': has_resources, 'findings': findings})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/graid/reset', methods=['POST'])
def reset_graid_resources():
    global benchmark_running
    if benchmark_running:
        return jsonify({'success': False, 'error': 'Cannot reset while benchmark is running'}), 400
        
    try:
        config = None
        if request.json:
            config = request.json.get('config')
            
        if not config:
            config = ConfigManager.load_config()
            
        executor = RemoteExecutor(config)
        results = []
        print("DEBUG: Starting Graid resources reset...", flush=True)
        
        # 1. Delete VDs
        print("DEBUG: Checking VDs...", flush=True)
        res_vd = executor.run(['graidctl', 'ls', 'vd', '--format', 'json'], capture_output=True, text=True)
        if res_vd.returncode == 0:
            try:
                vds = parse_graidctl_json(res_vd.stdout).get('Result', [])
                print(f"DEBUG: Found VDs: {vds}", flush=True)
                for vd in vds:
                    dg_id = vd.get('DgId')
                    vd_id = vd.get('VdId')
                    if dg_id is not None and vd_id is not None:
                        cmd = ['graidctl', 'del', 'vd', str(dg_id), str(vd_id), '--confirm-to-delete']
                        print(f"DEBUG: Executing: {' '.join(cmd)}", flush=True)
                        del_res = executor.run(cmd, capture_output=True, text=True)
                        print(f"DEBUG: VD Delete output: stdout='{del_res.stdout.strip()}', stderr='{del_res.stderr.strip()}'", flush=True)
                        results.append(f"Deleted VD {vd_id} in DG {dg_id}")
            except Exception as e:
                print(f"DEBUG: VD Parsing error: {e}", flush=True)

        # 2. Delete DGs
        print("DEBUG: Checking DGs...", flush=True)
        res_dg = executor.run(['graidctl', 'ls', 'dg', '--format', 'json'], capture_output=True, text=True)
        if res_dg.returncode == 0:
            try:
                dgs = parse_graidctl_json(res_dg.stdout).get('Result', [])
                print(f"DEBUG: Found DGs: {dgs}", flush=True)
                for dg in dgs:
                    dg_id = dg.get('DgId')
                    if dg_id is not None:
                        cmd = ['graidctl', 'del', 'dg', str(dg_id), '--confirm-to-delete']
                        print(f"DEBUG: Executing: {' '.join(cmd)}", flush=True)
                        del_res = executor.run(cmd, capture_output=True, text=True)
                        print(f"DEBUG: DG Delete output: stdout='{del_res.stdout.strip()}', stderr='{del_res.stderr.strip()}'", flush=True)
                        results.append(f"Deleted DG {dg_id}")
            except Exception as e:
                print(f"DEBUG: DG Parsing error: {e}", flush=True)

        # 3. Delete PDs
        print("DEBUG: Checking PDs...", flush=True)
        res_pd = executor.run(['graidctl', 'ls', 'pd', '--format', 'json'], capture_output=True, text=True)
        if res_pd.returncode == 0:
            try:
                pds = parse_graidctl_json(res_pd.stdout).get('Result', [])
                print(f"DEBUG: Found PDs: {pds}", flush=True)
                if pds:
                    pd_ids = [p.get('PdId') for p in pds if p.get('PdId') is not None]
                    if pd_ids:
                        min_pd = min(pd_ids)
                        max_pd = max(pd_ids)
                        pd_range = f"{min_pd}-{max_pd}"
                        cmd = ['graidctl', 'del', 'pd', pd_range]
                        print(f"DEBUG: Executing: {' '.join(cmd)}", flush=True)
                        del_res = executor.run(cmd, capture_output=True, text=True)
                        print(f"DEBUG: PD Delete output: stdout='{del_res.stdout.strip()}', stderr='{del_res.stderr.strip()}'", flush=True)
                        results.append(f"Deleted PDs in range {pd_range}")
            except Exception as e:
                print(f"DEBUG: PD Parsing error: {e}", flush=True)

        return jsonify({'success': True, 'message': 'Reset complete', 'details': results})
    except Exception as e:
        print(f"Error during reset: {e}", flush=True)
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
        return jsonify({'success': True, 'message': 'Benchmark stopped'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        benchmark_running = False
        BenchmarkState.clear()
        stop_giostat_monitoring()
        socketio.emit('status', {
            'status': 'completed',
            'message': 'Benchmark stopped by user',
            'timestamp': datetime.now().isoformat()
        })
        socketio.emit('run_status_update', {'status': 'READY'})


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
             # Strip common prefixes that scripts might send
             if output_dir.startswith('../results/'):
                 output_dir = output_dir[len('../results/'):]
             elif output_dir.startswith('./results/'):
                 output_dir = output_dir[len('./results/'):]
             elif output_dir.startswith('./'):
                 output_dir = output_dir[2:]
             
             # Security check: ensure no '..' to escape results dir
             if '..' in output_dir:
                 return jsonify({'success': False, 'error': 'Invalid path'}), 400
                 
             save_dir = RESULTS_DIR / output_dir / 'report_view'
        else:
             save_dir = RESULTS_DIR / 'report_view'
             
        save_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{test_name}_report_view.png"
        file_path = save_dir / filename
        
        with open(file_path, 'wb') as f:
            f.write(image_binary)
            
        print(f"Snapshot saved to {file_path}", flush=True)

        # Sync to remote if needed
        config = ConfigManager.load_config()
        executor = RemoteExecutor(config)
        if executor.is_remote:
             try:
                 # Map local path to remote path
                 remote_save_dir = executor._to_remote_path(str(save_dir))
                 executor.run(['mkdir', '-p', remote_save_dir])
                 executor.sync_to_remote(str(file_path), str(save_dir / filename))
                 print(f"Snapshot synced to remote: {remote_save_dir}/{filename}", flush=True)
             except Exception as e:
                 print(f"Error syncing snapshot to remote: {e}", flush=True)

        return jsonify({'success': True, 'message': 'Snapshot saved'})
    except Exception as e:
        print(f"Error saving snapshot: {e}", flush=True)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/benchmark/status', methods=['GET'])
def get_benchmark_status():
    global benchmark_running
    
    # If we think it's running, return current state
    if benchmark_running:
        return jsonify({
            'success': True, 
            'data': {
                'running': True, 
                'progress': benchmark_manager.latest_progress,
                'stage_info': benchmark_manager.current_stage_info,
                'timestamp': datetime.now().isoformat()
            }
        })
    
    # If not running locally, check persistent state file for recovery
    saved_state = BenchmarkState.load()
    if saved_state:
        try:
            config = saved_state.get('config', {})
            executor = RemoteExecutor(config)
            
            # Check if benchmark script is still running on remote
            res = executor.run(['pgrep', '-f', 'graid-bench.sh'], capture_output=True, text=True)
            if res.returncode == 0:
                # Remote benchmark is still running! Restore state
                benchmark_running = True
                print(f"DEBUG: Recovered running benchmark from persistent state", flush=True)
                
                # Try to restore progress from saved state
                progress = saved_state.get('progress', benchmark_manager.latest_progress)
                if progress:
                    benchmark_manager.latest_progress = progress
                
                return jsonify({
                    'success': True, 
                    'data': {
                        'running': True, 
                        'progress': benchmark_manager.latest_progress,
                        'stage_info': benchmark_manager.current_stage_info,
                        'recovered': True,
                        'timestamp': datetime.now().isoformat()
                    }
                })
            else:
                # Remote benchmark finished, clear state
                print(f"DEBUG: Persistent state exists but remote benchmark not running, clearing", flush=True)
                BenchmarkState.clear()
        except Exception as e:
            print(f"DEBUG: Error checking remote state: {e}", flush=True)
    
    return jsonify({
        'success': True, 
        'data': {
            'running': False, 
            'progress': None,
            'timestamp': datetime.now().isoformat()
        }
    })


@app.route('/api/results', methods=['GET'])
def get_results():
    try:
        results = []
        if RESULTS_DIR.exists():
            for result_item in RESULTS_DIR.iterdir():
                # Ignore hidden files/folders (starting with dot)
                if result_item.name.startswith('.'):
                    continue
                    
                # Handle archives
                allowed_extensions = ('.tar', '.tar.gz', '.tgz', '.json')
                if result_item.is_file() and result_item.name.lower().endswith(allowed_extensions):
                     results.append({
                         'name': result_item.name, 
                         'type': 'archive', 
                         'created': datetime.fromtimestamp(result_item.stat().st_mtime).isoformat(), 
                         'size': result_item.stat().st_size
                     })
                elif result_item.is_dir():
                    # Filter: Only include folders that contain at least one CSV file or have a relevant name pattern
                    # This prevents intermediate/empty folders from cluttering the UI
                    has_csv = any(result_item.rglob('*.csv'))
                    is_result_folder = result_item.name.endswith('-result')
                    
                    if has_csv or is_result_folder:
                        result_info = {
                            'name': result_item.name, 
                            'type': 'folder', 
                            'created': datetime.fromtimestamp(result_item.stat().st_mtime).isoformat(), 
                            'files': []
                        }
                        for file in result_item.rglob('*'):
                            if file.is_file():
                                result_info['files'].append({
                                    'name': file.name, 
                                    'path': str(file.relative_to(RESULTS_DIR)), 
                                    'size': file.stat().st_size
                                })
                        results.append(result_info)
        return jsonify({'success': True, 'data': results})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/results/<path:filename>', methods=['GET'])
def get_result_file(filename):
    try:
        response = send_from_directory(RESULTS_DIR, filename)
        if filename.lower().endswith(('.png', '.jpg', '.jpeg')):
             response.headers['Cache-Control'] = 'public, max-age=86400'
        return response
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 404

@app.route('/api/results/<result_name>/download', methods=['GET'])
def download_result(result_name):
    try:
        # Check RESULTS_DIR
        target = RESULTS_DIR / result_name
        if target.exists() and target.is_file():
            return send_from_directory(RESULTS_DIR, result_name, as_attachment=True)
        
        # Check if it corresponds to an archive in RESULTS_DIR (if result_name came without extension)
        for ext in ['.tar', '.tar.gz', '.tgz', '.json']:
            archive_target = RESULTS_DIR / f"{result_name}{ext}"
            if archive_target.exists():
                return send_from_directory(RESULTS_DIR, f"{result_name}{ext}", as_attachment=True)
            
        return jsonify({'success': False, 'error': 'Result file not found'}), 404
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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

        elif result_path.is_file() and result_path.name.lower().endswith(('.tar', '.tar.gz', '.tgz')):
            # Handle tar file
            import tarfile
            with tarfile.open(result_path, 'r') as tar:
                # 1. Try to find the summary CSV first
                summary_csv_member = None
                for member in tar.getmembers():
                    if 'result/fio-test-r-' in member.name and member.name.endswith('.csv'):
                        summary_csv_member = member
                        break
                
                target_members = []
                if summary_csv_member:
                    target_members.append(summary_csv_member)
                else:
                    # Fallback: Find all individual fio/diskspd CSV files
                    for member in tar.getmembers():
                        if member.name.endswith('.csv') and ('fio-test' in member.name or 'diskspd-test' in member.name):
                            target_members.append(member)
                
                req_type = request.args.get('type')
                
                for member in target_members:
                    try:
                        f = tar.extractfile(member)
                        if f is None: continue
                        
                        content = f.read().decode('utf-8', errors='ignore')
                        reader = csv.DictReader(content.splitlines())
                        
                        for row in reader:
                            # Use member name as fallback filename if column missing
                            filename_col = row.get('filename') or row.get('file_name') or member.name
                            
                            # Filtering Logic
                            if req_type == 'baseline':
                                if 'SingleTest' not in filename_col and '/PD/' not in member.name.upper():
                                    continue
                            elif req_type == 'graid':
                                if 'RAID' not in filename_col and '/VD/' not in member.name.upper():
                                    continue
                            
                            # Ensure Workload is set
                            if 'Workload' not in row:
                                row['Workload'] = get_workload_name(row)
                            
                            # Try to extract RAID info if missing (important for charts)
                            if not row.get('RAID_type') or row.get('RAID_type') == 'N/A':
                                # Try parsing from filename_col or member name
                                parts = (filename_col or member.name).split('-')
                                for p in parts:
                                    if p.startswith('RAID'):
                                        row['RAID_type'] = p
                                    if p.endswith('PD'):
                                        row['PD_count'] = p.replace('PD', '')
                            
                            csv_data.append(row)
                    except Exception as e:
                        print(f"Error parsing tar member {member.name}: {e}")

        return jsonify({'success': True, 'data': csv_data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/results/<result_name>/images', methods=['GET'])
def get_result_images(result_name):
    try:
        result_path = RESULTS_DIR / result_name
        model_result_path = SCRIPT_DIR / f"{result_name}-result" / result_name
        
        target_path = None
        if result_path.exists():
            target_path = result_path
        elif model_result_path.exists():
            target_path = model_result_path
            
        if not target_path:
            return jsonify({'success': False, 'error': 'Result not found'}), 404
            
        images = []
        def parse_tags(img_path):
            tags = {
                'category': 'VD' if '/VD/' in img_path else 'PD' if '/PD/' in img_path else 'Other',
                'raid': 'Unknown',
                'workload': 'Unknown',
                'bs': 'Unknown',
                'status': 'Normal'
            }
            
            # Pattern: graid-SR-ULTRA-AD-RAW-RAID6-1VD-24PD-S-Micron-D-afterdiscard-seqwrite-grai-Rebuild
            filename = Path(img_path).stem
            parts = filename.split('-')
            
            # RAID
            for p in parts:
                if p.startswith('RAID'): tags['raid'] = p.replace('RAID', 'RAID ')
            
            # Status
            if 'Normal' in filename: tags['status'] = 'Normal'
            elif 'Rebuild' in filename: tags['status'] = 'Rebuild'
            
            # Workload & BS
            if 'seqwrite' in filename: tags['workload'] = 'Seq Write'
            elif 'seqread' in filename: tags['workload'] = 'Seq Read'
            elif 'randread' in filename: tags['workload'] = 'Rand Read'
            elif 'randwrite' in filename: tags['workload'] = 'Rand Write'
            elif 'randrw73' in filename: tags['workload'] = 'Mix(70/30)'
            elif 'randrw55' in filename: tags['workload'] = 'Mix(50/50)'
            
            # Extract BS from filename more robustly
            known_bs = ['4k', '8k', '16k', '32k', '64k', '128k', '256k', '512k', '1m', '1M', '2m', '4m']
            for b in known_bs:
                if f"-{b}-" in filename or filename.endswith(f"-{b}"):
                    tags['bs'] = b.upper()
                    break
            
            # Fallback for BS if not found in filename but workload is known
            if tags['bs'] == 'Unknown':
                if 'rand' in tags['workload'].lower(): tags['bs'] = '4K'
                elif 'seq' in tags['workload'].lower(): tags['bs'] = '1M'
            
            if tags['category'] == 'PD':
                tags['raid'] = 'BASELINE'
                
            return tags

        if target_path.is_dir():
            for img_file in target_path.rglob('*'):
                if img_file.is_file() and img_file.suffix.lower() in ['.png', '.jpg', '.jpeg']:
                    if 'report_view' in str(img_file):
                        rel_path = str(img_file.relative_to(RESULTS_DIR if result_path.exists() else SCRIPT_DIR))
                        tags = parse_tags(str(img_file))
                        images.append({
                            'name': img_file.name,
                            'url': f"/api/results/{rel_path}",
                            'tags': tags
                        })
        elif target_path.is_file() and target_path.name.lower().endswith(('.tar', '.tar.gz', '.tgz')):
            import tarfile
            
            # Cache directory for this specific tar
            result_cache_dir = CACHE_DIR / result_name
            result_cache_dir.mkdir(parents=True, exist_ok=True)
            
            with tarfile.open(target_path, 'r') as tar:
                for member in tar.getmembers():
                    if member.isfile() and member.name.lower().endswith(('.png', '.jpg', '.jpeg')):
                        if 'report_view' in member.name:
                             # Extract to cache if not exists (flatten name to avoid collision)
                             cache_filename = member.name.replace('/', '_')
                             cache_file = result_cache_dir / cache_filename
                             if not cache_file.exists():
                                 with tar.extractfile(member) as f_in:
                                     with open(cache_file, 'wb') as f_out:
                                         f_out.write(f_in.read())
                             
                             tags = parse_tags(member.name)
                             images.append({
                                'name': cache_filename,
                                'url': f"/api/results/.cache/{result_name}/{cache_filename}",
                                'tags': tags
                            })
        
        response = jsonify({'success': True, 'images': images})
        response.headers['Cache-Control'] = 'public, max-age=3600'
        return response
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/results/<result_name>/clear-cache', methods=['POST'])
def clear_result_cache(result_name):
    try:
        import shutil
        target = CACHE_DIR / result_name
        if target.exists():
            shutil.rmtree(target)
        return jsonify({'success': True})
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
    # Try to recover state on startup
    state = BenchmarkState.load()
    if state:
        benchmark_manager.recover_state(state)
        
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true' or os.environ.get('FLASK_ENV') == 'development'
    socketio.run(app, host='0.0.0.0', port=50071,
                 debug=debug_mode, allow_unsafe_werkzeug=True)

