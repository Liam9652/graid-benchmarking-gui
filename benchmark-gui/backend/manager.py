"""BenchmarkManager — owns the benchmark worker thread and giostat watchdog.

Single source of truth for `running`, `process`, `worker_thread`,
`giostat_*`, and the active state file. try_start guards a single
running slot under `_start_lock` (B2). stop_benchmark tears worker +
giostat down in order (B1).
"""

import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import config as _cfg
from config import (
    BASE_DIR,
    LOGS_DIR,
    REMOTE_BASE_DIR,
    RESULTS_DIR,
    SCRIPT_DIR,
    WORKLOAD_MAP,
    generate_run_id,
    logger,
    strip_ansi,
)
from state import BenchmarkState, ConfigManager, sanitize_config
from executor import RemoteExecutor
from monitor import start_giostat_monitoring, stop_giostat_monitoring


def is_remote_benchmark_alive(executor, saved_pid=None):
    """Check whether the recovered benchmark is still running on the remote.

    Prefers `kill -0 <pid>` against the PID captured at launch, since pgrep can
    match unrelated processes whose argv happens to contain `graid-bench.sh`.
    Falls back to the legacy pgrep probe when no PID was persisted (older
    state file) so recovery still works after an upgrade.
    """
    if saved_pid:
        try:
            res = executor.run(
                ['kill', '-0', str(saved_pid)],
                capture_output=True,
                text=True,
            )
            return res.returncode == 0
        except Exception as exc:
            logger.debug("kill -0 probe failed, falling back to pgrep: %s", exc)
    res = executor.run(
        ['pgrep', '-f', 'graid-bench.sh'],
        capture_output=True,
        text=True,
    )
    return res.returncode == 0


class BenchmarkManager:
    def __init__(self, executor_factory=None):
        # executor_factory lets tests inject a fake RemoteExecutor that
        # records SSH calls without a real DUT. Production code passes None
        # and gets the real RemoteExecutor. (A3 in AUDIT.md)
        self._executor_factory = executor_factory or RemoteExecutor
        self.process = None
        self.worker_thread = None
        self.running = False
        self.active_run_id = None
        self.session_id = None
        self.runtime_config = None
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
        self._lock = threading.Lock()
        # Serializes start() check-and-set + stop() teardown so two concurrent
        # callers cannot both observe running=False and launch a worker.
        self._start_lock = threading.Lock()
        # Serializes BenchmarkState read-modify-write from worker tick saves
        # vs. stop()'s clear, so a tick cannot resurrect cleared state.
        self._state_lock = threading.Lock()
        # giostat sidecar lifecycle is owned by BenchmarkManager so stop()
        # can deterministically terminate the subprocess and join the thread.
        self.giostat_process = None
        self.giostat_thread = None
        self.stop_giostat_event = threading.Event()

    def try_start(self, config, session_id, run_id):
        """Atomically claim the running slot and launch the worker thread.

        Returns the launched Thread on success, or None if a benchmark is
        already running. Caller is responsible for emitting any UI events.
        """
        with self._start_lock:
            if self.running:
                return None
            self.running = True
            self.active_run_id = run_id
            self.session_id = session_id
            self.runtime_config = dict(config)
            thread = threading.Thread(
                target=self.run_benchmark,
                args=(config, session_id, run_id),
                daemon=True,
            )
            self.worker_thread = thread
        thread.start()
        return thread

    def stop_benchmark(self, join_timeout=5):
        """Terminate the worker process, join the worker thread, then clear state.

        Returns the run_id that was stopped, or None if nothing was running.
        """
        with self._start_lock:
            if not self.running:
                return None
            run_id = self.active_run_id
            proc = self.process
            thread = self.worker_thread
            # Flip the flag early so any in-flight tick save sees running=False
            # under _state_lock and skips writing.
            self.running = False

        if proc is not None:
            try:
                proc.terminate()
            except Exception as exc:
                logger.warning("benchmark process terminate failed: %s", exc)
            try:
                proc.wait(timeout=1)
            except Exception:
                try:
                    proc.kill()
                except Exception as exc:
                    logger.warning("benchmark process kill failed: %s", exc)

        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)
            if thread.is_alive():
                logger.warning("benchmark worker thread did not exit within %ss", join_timeout)

        # _state_lock pairs with the tick save's lock so any in-flight save
        # completes before we clear the file.
        with self._state_lock:
            BenchmarkState.clear()

        with self._start_lock:
            self.process = None
            self.worker_thread = None
            self.active_run_id = None
            self.session_id = None
            self.runtime_config = None

        stop_giostat_monitoring()
        return run_id

    def recover_state(self, state):
        try:
            self.current_log_file = Path(state['log_file'])
            session_id = state['session_id']
            config = state['config']
            run_id = state.get('run_id')

            # Restore stage info if available
            self.current_stage_info = state.get('stage_info', {'stage': '', 'label': ''})

            # The saved config has no password (stripped for security).
            # Without credentials we cannot reconnect — clear state and bail out.
            if config.get('REMOTE_MODE') and not config.get('DUT_PASSWORD'):
                logger.info("Benchmark state found but no credentials available for recovery — clearing state.")
                BenchmarkState.clear()
                return False

            executor = self._executor_factory(config)

            # Check if remote process is alive
            # Prefer the captured PID from the saved state; fall back to pgrep
            # only when older state files lack a pid (e.g., across an upgrade).
            saved_pid = state.get('pid')
            if is_remote_benchmark_alive(executor, saved_pid):
                logger.info("Recovering active benchmark on session %s", session_id)
                with self._start_lock:
                    self.running = True
                    self.active_run_id = run_id
                    self.session_id = session_id
                    self.runtime_config = config
                
                # Start a thread to wait for completion and sync
                thread = threading.Thread(
                    target=self._wait_for_completion,
                    args=(executor, session_id, config, saved_pid)
                )
                thread.daemon = True
                thread.start()

                # Restart giostat monitoring
                start_giostat_monitoring(session_id, executor)

                # Emit status to UI
                _cfg.socketio.emit('status', {
                    'status': 'started',
                    'message': 'Benchmark is already running (Recovered)',
                    'timestamp': datetime.now().isoformat()
                }, room=session_id)
                
                return True
            else:
                logger.info("Active state found but no remote benchmark process detected — clearing state.")
                BenchmarkState.clear()
        except Exception as e:
            logger.error("Error during state recovery: %s", e)
            try:
                BenchmarkState.clear()
            except Exception as clear_err:
                logger.error("Error clearing benchmark state after recovery failure: %s", clear_err)
        return False

    def _wait_for_completion(self, executor, session_id, config, saved_pid=None):
        try:
            # Poll until the captured PID dies (or pgrep fails on legacy state).
            while True:
                if not is_remote_benchmark_alive(executor, saved_pid):
                    break
                time.sleep(10)
            
            # Sync back
            if executor.is_remote:
                try:
                    executor.sync_from_remote(str(RESULTS_DIR.parent), str(RESULTS_DIR))
                    executor.sync_from_remote(str(LOGS_DIR.parent), str(LOGS_DIR))
                except Exception as e:
                    logger.error("Error syncing back after recovery: %s", e)
                    
            _cfg.socketio.emit('status', {
                'status': 'completed',
                'message': 'Benchmark completed (recovered)',
                'timestamp': datetime.now().isoformat(),
                'run_id': self.active_run_id,
            }, room=session_id)
            
        finally:
            with self._start_lock:
                self.running = False
                self.active_run_id = None
                self.session_id = None
                self.runtime_config = None
            BenchmarkState.clear()
            stop_giostat_monitoring()

    def run_benchmark(self, config, session_id, run_id=None):
        run_id = run_id or generate_run_id()
        executor = None
        try:
            ConfigManager.save_config(config)
            executor = self._executor_factory(config)
            with self._start_lock:
                self.running = True
                self.active_run_id = run_id
                self.session_id = session_id
                self.runtime_config = dict(config)
            
            # Start giostat monitoring
            start_giostat_monitoring(session_id, executor)

            # Sync scripts to remote if in remote mode
            if executor.is_remote:
                _cfg.socketio.emit('status', {
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
                
                checksum = executor.run(['md5sum', str(SCRIPT_DIR / 'graid-bench.sh')], capture_output=True, text=True)
                logger.debug("Remote script checksum: %s", checksum.stdout.strip())

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

            _cfg.socketio.emit('status', {
                'status': 'started',
                'message': 'Benchmark started',
                'timestamp': datetime.now().isoformat(),
                'run_id': run_id,
            }, room=session_id)

            self.latest_progress = {
                'percentage': 0,
                'elapsed': 0,
                'remaining': 0,
                'current_step': 0,
                'total_steps': 0
            }

            self.current_log_file = LOGS_DIR / f"benchmark_{int(time.time())}_{run_id}.log"
            log_file = self.current_log_file
            
            start_time = time.time()
            
            # Save active state for recovery
            BenchmarkState.save({
                'run_id': run_id,
                'session_id': session_id,
                'log_file': str(log_file),
                'config': sanitize_config(config),
                'start_time': start_time,
                'status': 'started'
            })

            script_path = SCRIPT_DIR / 'graid-bench.sh'
            if executor.is_remote:
                script_path = executor._to_remote_path(str(script_path))
                
            cmd = ['bash', str(script_path)]

            # Local-only: prepend backend venv/bin to PATH so the script picks
            # up the same python/tools the backend was launched with. Remote
            # mode relies on the DUT's own PATH (python/tools resolved via
            # check_dependencies before launch).
            env = os.environ.copy()
            if not executor.is_remote:
                venv_bin = BASE_DIR / 'venv' / 'bin'
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
                        logger.info("Total estimated seconds: %d", total_est_seconds)
            except Exception as e:
                logger.warning("Error getting estimated time: %s", e)

            # Open log file for writing
            with open(log_file, 'w') as log:
                self.process = executor.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    cwd=str(SCRIPT_DIR), env=env, text=True, bufsize=1
                )

                # Persist the PID so recover_state can use `kill -0 <pid>`
                # instead of pgrep, which can false-match unrelated processes.
                process_pid = getattr(self.process, 'pid', None)
                BenchmarkState.save({
                    'run_id': run_id,
                    'session_id': session_id,
                    'log_file': str(log_file),
                    'config': sanitize_config(config),
                    'start_time': start_time,
                    'status': 'started',
                    'pid': process_pid,
                })

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
                                 _cfg.socketio.emit('bench_log', {'line': msg}, room=session_id)

                            logger.debug("BENCH_LOG: %s", msg)

                            # Detect STATUS markers
                            if "STATUS: STATE:" in msg:
                                 try:
                                     state = msg.split("STATUS: STATE:")[1].strip()
                                     logger.info("DETECTED STATE: %s", state)
                                     _cfg.socketio.emit('run_status_update', {
                                        'status': state,
                                        'timestamp': datetime.now().isoformat()
                                     }, room=session_id)
                                 except Exception as e:
                                     logger.warning("Error parsing state: %s", e)

                            elif "STATUS: ERROR:" in msg:
                                 try:
                                     error_msg = msg.split("STATUS: ERROR:")[1].strip()
                                     logger.warning("DETECTED ERROR: %s", error_msg)
                                     self.last_error = error_msg
                                 except Exception as e:
                                     logger.warning("Error parsing error message: %s", e)


                            elif "STATUS: STAGE_PD_START" in msg:
                                 logger.info("DETECTED STAGE PD START")
                                 current_base_label = 'Baseline Performance Test\n'
                                 self.current_stage_info = {'stage': 'PD', 'label': current_base_label}
                                 _cfg.socketio.emit('status_update', {
                                    'stage': 'PD',
                                    'label': current_base_label,
                                    'timestamp': datetime.now().isoformat()
                                }, room=session_id)
                                 # Update persistent state
                                 BenchmarkState.save({
                                     'session_id': session_id,
                                     'run_id': run_id,
                                     'log_file': str(self.current_log_file),
                                     'config': sanitize_config(config),
                                     'start_time': start_time,
                                     'status': 'started',
                                     'stage_info': self.current_stage_info,
                                     'pid': process_pid,
                                 })

                            elif "STATUS: STAGE_VD_START" in msg:
                                 logger.info("DETECTED STAGE VD START")
                                 current_base_label = 'RAID Performance Test\n'
                                 self.current_stage_info = {'stage': 'VD', 'label': current_base_label}
                                 _cfg.socketio.emit('status_update', {
                                    'stage': 'VD',
                                    'label': current_base_label,
                                    'timestamp': datetime.now().isoformat()
                                }, room=session_id)
                                 # Update persistent state
                                 BenchmarkState.save({
                                     'session_id': session_id,
                                     'run_id': run_id,
                                     'log_file': str(self.current_log_file),
                                     'config': sanitize_config(config),
                                     'start_time': start_time,
                                     'status': 'started',
                                     'stage_info': self.current_stage_info,
                                     'pid': process_pid,
                                 })

                            elif "STATUS: STAGE_MD_START" in msg:
                                 logger.info("DETECTED STAGE MD START")
                                 current_base_label = 'MDADM Performance Test\n'
                                 self.current_stage_info = {'stage': 'MD', 'label': current_base_label}
                                 _cfg.socketio.emit('status_update', {
                                    'stage': 'MD',
                                    'label': current_base_label,
                                    'timestamp': datetime.now().isoformat()
                                }, room=session_id)
                                 # Update persistent state
                                 BenchmarkState.save({
                                     'session_id': session_id,
                                     'run_id': run_id,
                                     'log_file': str(self.current_log_file),
                                     'config': sanitize_config(config),
                                     'start_time': start_time,
                                     'status': 'started',
                                     'stage_info': self.current_stage_info,
                                     'pid': process_pid,
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
                                    logger.info("DETECTED WORKLOAD: %s -> %s", filename, new_label)
                                    stage_code = 'PD' if 'Baseline' in current_base_label else 'MD' if 'MDADM' in current_base_label else 'VD'
                                    
                                    self.current_stage_info = {'stage': stage_code, 'label': new_label}
                                    _cfg.socketio.emit('status_update', {
                                        'stage': stage_code,
                                        'label': new_label,
                                        'timestamp': datetime.now().isoformat()
                                    }, room=session_id)
                                    # Update persistent state
                                    BenchmarkState.save({
                                        'session_id': session_id,
                                        'run_id': run_id,
                                        'log_file': str(self.current_log_file),
                                        'config': sanitize_config(config),
                                        'start_time': start_time,
                                        'status': 'started',
                                        'stage_info': self.current_stage_info,
                                        'pid': process_pid,
                                    })
                                except Exception as e:
                                    logger.warning("Error parsing workload: %s", e)

                            elif "STATUS: TOTAL_STEPS:" in msg:
                                try:
                                    self.total_steps = int(msg.split("STATUS: TOTAL_STEPS:")[1].strip())
                                    self.current_step = 0
                                    logger.debug("Total steps set to %d", self.total_steps)
                                except Exception:
                                    pass

                            elif "STATUS: SNAPSHOT:" in msg:
                                 try:
                                     # Format: STATUS: SNAPSHOT: test_name="name" output_dir="dir"
                                     test_match = re.search(r'test_name="([^"]+)"', msg)
                                     dir_match = re.search(r'output_dir="([^"]+)"', msg)
                                     
                                     tn = test_match.group(1) if test_match else "unknown"
                                     od = dir_match.group(1) if dir_match else ""
                                     
                                     logger.info("TRIGGER SNAPSHOT -> test=%s, dir=%s", tn, od)
                                     _cfg.socketio.emit('snapshot_request', {
                                         'test_name': tn,
                                         'output_dir': od
                                     }, room=session_id)
                                 except Exception as e:
                                     logger.warning("Error parsing snapshot marker: %s", e)

                            elif "STATUS: DEVICE_START:" in msg:
                                try:
                                    dev = msg.split("STATUS: DEVICE_START:")[1].strip()
                                    _cfg.socketio.emit('device_discard_update', {
                                        'device': dev,
                                        'state': 'started',
                                        'timestamp': datetime.now().isoformat()
                                    }, room=session_id)
                                except Exception as e:
                                    logger.warning("Error parsing DEVICE_START: %s", e)

                            elif "STATUS: DEVICE_DONE:" in msg:
                                try:
                                    dev = msg.split("STATUS: DEVICE_DONE:")[1].strip()
                                    _cfg.socketio.emit('device_discard_update', {
                                        'device': dev,
                                        'state': 'done',
                                        'timestamp': datetime.now().isoformat()
                                    }, room=session_id)
                                except Exception as e:
                                    logger.warning("Error parsing DEVICE_DONE: %s", e)

                            elif "STATUS: DEVICE_STUCK:" in msg:
                                try:
                                    dev = msg.split("STATUS: DEVICE_STUCK:")[1].strip()
                                    logger.warning("DEVICE_STUCK detected: %s", dev)
                                    _cfg.socketio.emit('device_stuck', {
                                        'device': dev,
                                        'timestamp': datetime.now().isoformat()
                                    }, room=session_id)
                                except Exception as e:
                                    logger.warning("Error parsing DEVICE_STUCK: %s", e)

                            elif "STATUS: DEVICE_UNSTUCK:" in msg:
                                try:
                                    dev = msg.split("STATUS: DEVICE_UNSTUCK:")[1].strip()
                                    _cfg.socketio.emit('device_unstuck', {
                                        'device': dev,
                                        'timestamp': datetime.now().isoformat()
                                    }, room=session_id)
                                except Exception as e:
                                    logger.warning("Error parsing DEVICE_UNSTUCK: %s", e)

                            elif "STATUS: TICK" in msg:
                                try:
                                    self.current_step += 1
                                    percentage = 0
                                    elapsed = int(time.time() - start_time)
                                    if self.total_steps > 0:
                                        percentage = (self.current_step / self.total_steps) * 100

                                    # Refined remaining time logic
                                    remaining = 0
                                    if total_est_seconds > 0:
                                        # Use initial estimate minus elapsed as baseline
                                        est_remaining = total_est_seconds - elapsed
                                        if est_remaining < 0: est_remaining = 0
                                        
                                        if percentage > 10:
                                            # After 10% progress, blend with extrapolation for real-time correction
                                            # This avoids massive drops due to fast init/preconditioning steps
                                            extrapolated_total = elapsed / (percentage / 100)
                                            extrapolated_remaining = int(extrapolated_total - elapsed)
                                            
                                            # Transition factor (0.0 at 10% progress, 1.0 at 100% progress)
                                            alpha = (percentage - 10) / 90
                                            remaining = int(est_remaining * (1 - alpha) + extrapolated_remaining * alpha)
                                        else:
                                            # Early stage (<10%): prioritize initial estimate
                                            remaining = est_remaining
                                    elif percentage > 0:
                                        # Fallback to pure extrapolation if no initial estimate was parsed
                                        total_projected = elapsed / (percentage / 100)
                                        remaining = int(total_projected - elapsed)
                                    
                                    if remaining < 0: remaining = 0
                                    
                                    self.latest_progress = {
                                        'current_step': self.current_step,
                                        'total_steps': self.total_steps,
                                        'percentage': round(percentage, 2),
                                        'elapsed': elapsed,
                                        'remaining': remaining,
                                        'timestamp': datetime.now().isoformat()
                                    }
                                    _cfg.socketio.emit('progress_update', self.latest_progress, room=session_id)
                                    
                                    # Update persistent state with latest progress (every 10 ticks to reduce I/O).
                                    # Hold _state_lock so this read-modify-write doesn't race with stop_benchmark()'s clear().
                                    if self.current_step % 10 == 0:
                                        with self._state_lock:
                                            if self.running:
                                                try:
                                                    saved = BenchmarkState.load() or {}
                                                    saved['progress'] = self.latest_progress
                                                    BenchmarkState.save(saved)
                                                except Exception as exc:
                                                    logger.debug("tick state save skipped: %s", exc)
                                except Exception as e:
                                    logger.warning("Error handling progress tick: %s", e)
                    else:
                        # No data or EOF
                        if self.process.poll() is not None:
                             # Process ended
                             break
                
                # Wait for completion
                self.process.wait()
                logger.info("BENCH_PROCESS_EXIT: rc=%d", self.process.returncode)


            if self.process.returncode == 0:
                _cfg.socketio.emit('status', {
                    'status': 'completed',
                    'message': 'Benchmark completed',
                    'timestamp': datetime.now().isoformat(),
                    'run_id': run_id,
                }, room=session_id)
            else:
                fail_msg = self.last_error if self.last_error else f'Failed: {self.process.returncode} (No error captured)'
                _cfg.socketio.emit('status', {
                    'status': 'failed',
                    'message': fail_msg,
                    'timestamp': datetime.now().isoformat(),
                    'run_id': run_id,
                }, room=session_id)
        except Exception as e:
            _cfg.socketio.emit('error', {
                'message': str(e),
                'timestamp': datetime.now().isoformat(),
                'run_id': run_id,
            }, room=session_id)
        finally:
            if executor is not None and executor.is_remote:
                # Sync results and logs back from remote
                try:
                    executor.sync_from_remote(str(RESULTS_DIR.parent), str(RESULTS_DIR))
                    executor.sync_from_remote(str(LOGS_DIR.parent), str(LOGS_DIR))
                except Exception as e:
                    logger.error("Error syncing back results: %s", e)

            with self._start_lock:
                self.running = False
                self.process = None
                self.worker_thread = None
                self.active_run_id = None
                self.session_id = None
                self.runtime_config = None
            stop_giostat_monitoring()


benchmark_manager = BenchmarkManager()
