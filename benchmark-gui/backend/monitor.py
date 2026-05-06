"""giostat watchdog lifecycle.

Owns no state of its own — process/thread/event live on `benchmark_manager`
(B13 in AUDIT.md) so stop_benchmark() can deterministically tear them down.
benchmark_manager is imported lazily to break the manager↔monitor cycle.
"""

import subprocess
import threading
import time
from datetime import datetime

import config
from config import LOGS_DIR, logger, strip_ansi
from state import ConfigManager
from executor import RemoteExecutor


def start_giostat_monitoring(session_id, executor=None):
    from manager import benchmark_manager
    benchmark_manager.stop_giostat_event.clear()
    thread = threading.Thread(
        target=monitor_giostat,
        args=(session_id, executor),
        daemon=True,
    )
    benchmark_manager.giostat_thread = thread
    thread.start()


def stop_giostat_monitoring(join_timeout=3):
    from manager import benchmark_manager
    benchmark_manager.stop_giostat_event.set()
    proc = benchmark_manager.giostat_process
    if proc is not None:
        try:
            proc.terminate()
        except Exception as exc:
            logger.warning("giostat terminate failed: %s", exc)
        try:
            proc.wait(timeout=1)
        except Exception:
            try:
                proc.kill()
            except Exception as exc:
                logger.warning("giostat kill failed: %s", exc)
    thread = benchmark_manager.giostat_thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=join_timeout)
        if thread.is_alive():
            logger.warning("giostat thread did not exit within %ss", join_timeout)
    benchmark_manager.giostat_process = None
    benchmark_manager.giostat_thread = None


def monitor_giostat(session_id, executor=None):
    from manager import benchmark_manager

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
        proc = executor.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1
        )
        benchmark_manager.giostat_process = proc

        headers = None
        header_map = {}

        while not benchmark_manager.stop_giostat_event.is_set() and proc.poll() is None:
            line = proc.stdout.readline()
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
            except OSError as e:
                logger.debug("giostat log rotation skipped: %s", e)
            
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
                                try:
                                    return float(parts[header_map[k]])
                                except (ValueError, IndexError):
                                    pass
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
                    
                    config.socketio.emit('giostat_data_v2', data, room=session_id)
                    # Also keep v1 for simple terminal display if needed
                    config.socketio.emit('giostat_data', {'line': line}, room=session_id)
                except Exception as e:
                    logger.debug("Error parsing giostat line: %s", e)
                    config.socketio.emit('giostat_data', {'line': line}, room=session_id)
            else:
                # Fallback for raw lines
                config.socketio.emit('giostat_data', {'line': line}, room=session_id)
                
    except Exception as e:
        logger.error("Error in giostat monitoring: %s", e)
    finally:
        try:
            debug_log.write(f"--- giostat monitoring ended at {datetime.now().isoformat()} ---\n")
            debug_log.close()
        except (OSError, NameError) as e:
            logger.debug("giostat debug_log close failed: %s", e)
        proc = benchmark_manager.giostat_process
        if proc is not None:
            try:
                proc.terminate()
            except Exception as exc:
                logger.debug("giostat terminate skipped: %s", exc)
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except Exception as exc:
                    logger.debug("giostat kill skipped: %s", exc)
