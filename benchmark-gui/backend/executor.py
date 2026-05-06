"""RemoteExecutor — runs commands locally or remotely (paramiko/SCP).

When config has REMOTE_MODE=True and SSH credentials, RemoteExecutor SSHes
into the DUT; otherwise commands run as subprocesses on the host.

Popen() returns a RemoteProcess wrapping a paramiko channel; it supports
`text=True` via `_DecodingStream` (B8) and `wait(timeout=...)` via
`exit_status_ready()` polling (B12).
"""

import shlex
import subprocess
import threading
import time
from pathlib import Path

import paramiko
from scp import SCPClient

from config import BASE_DIR, REMOTE_BASE_DIR, logger


class _AutoUpdateHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """Auto-accept and update host keys for lab/DUT environments without blocking."""
    def missing_host_key(self, client, hostname, key):
        client._host_keys.add(hostname, key.get_name(), key)
        logger.warning("SSH: auto-accepted host key for %s (%s)", hostname, key.get_name())


class RemoteExecutor:
    """Handles command execution locally or remotely via SSH."""

    def __init__(self, config=None):
        self.config = config or {}
        self.is_remote = self.config.get('REMOTE_MODE', False)
        self.ssh = None
        self.is_root = False
        self.has_sudo = False
        self.need_sudo_password = False
        # Per-instance lock so concurrent RemoteExecutor instances do not
        # serialize unrelated SSH connects through one global lock.
        self._lock = threading.Lock()

    def _get_ssh_client(self):
        with self._lock:
            if self.ssh:
                try:
                    transport = self.ssh.get_transport()
                    if transport and transport.is_active():
                        return self.ssh
                except Exception:
                    pass
                # Connection dead, clean up
                try:
                    self.ssh.close()
                except Exception:
                    pass
                self.ssh = None
            
            hostname = self.config.get('DUT_IP')
            if not hostname:
                raise ValueError("Remote mode enabled but DUT IP Address is missing in configuration.")
                
            username = self.config.get('DUT_USER', 'root')
            password = self.config.get('DUT_PASSWORD')
            port = int(self.config.get('DUT_PORT', 22))
            
            logger.info("Connecting to remote DUT %s as %s...", hostname, username)
            try:
                # Phase 1: establish SSH connection (with host-key-change retry)
                self.ssh = paramiko.SSHClient()
                self.ssh.set_missing_host_key_policy(_AutoUpdateHostKeyPolicy())
                try:
                    self.ssh.connect(hostname, port=port, username=username, password=password,
                                     timeout=10, banner_timeout=15,
                                     look_for_keys=False, allow_agent=False)
                except paramiko.ssh_exception.SSHException as e:
                    err_str = str(e).lower()
                    if any(kw in err_str for kw in ('not found in known_hosts', 'key mismatch', 'host key')):
                        logger.warning("SSH host key conflict for %s, clearing and retrying: %s", hostname, e)
                        try: self.ssh.close()
                        except Exception: pass
                        self.ssh = paramiko.SSHClient()
                        self.ssh.set_missing_host_key_policy(_AutoUpdateHostKeyPolicy())
                        self.ssh.connect(hostname, port=port, username=username, password=password,
                                         timeout=10, look_for_keys=False, allow_agent=False)
                    else:
                        raise

                # Phase 2: check permissions
                self.is_root = False
                self.has_sudo = False
                self.need_sudo_password = False

                _, stdout, _ = self.ssh.exec_command('id -u')
                uid = stdout.read().decode().strip()
                if uid == '0':
                    self.is_root = True
                else:
                    # 1. Try passwordless sudo first
                    stdin, stdout, stderr = self.ssh.exec_command('sudo -n id -u')
                    if stdout.channel.recv_exit_status() == 0:
                        sudo_uid = stdout.read().decode().strip()
                        if sudo_uid == '0':
                            self.has_sudo = True

                    # 2. If passwordless fails, try sudo with password if we have one
                    if not self.has_sudo and password:
                        stdin, stdout, stderr = self.ssh.exec_command('sudo -S id -u')
                        stdin.write(password + '\n')
                        stdin.flush()
                        if stdout.channel.recv_exit_status() == 0:
                            sudo_uid = stdout.read().decode().strip()
                            if sudo_uid == '0':
                                self.has_sudo = True
                                self.need_sudo_password = True
                                logger.info("Sudo with password verified for %s", username)

                    if not self.has_sudo:
                        self.ssh.close()
                        self.ssh = None
                        raise PermissionError(f"User '{username}' does not have root privileges or sudo access on {hostname}. Hardware control requires root access.")

                return self.ssh
            except Exception as e:
                if self.ssh:
                    try:
                        self.ssh.close()
                    except Exception:
                        pass
                self.ssh = None
                logger.error("SSH connection or permission check failed: %s", e)
                raise ConnectionError(f"Failed to connect or verify permissions on remote DUT {hostname}: {str(e)}")

    def _to_remote_path(self, path):
        if not self.is_remote:
            return path
        # Map local absolute path to remote /tmp/benchmark-gui based path
        path_obj = Path(path).resolve()
        base_obj = BASE_DIR.resolve()
        
        if path_obj.is_absolute():
            # If it's under our BASE_DIR, relative it
            try:
                rel = path_obj.relative_to(base_obj)
                res = str(REMOTE_BASE_DIR / rel)
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

        # Remote path historically swallowed the `text` / `bufsize` / `stderr`
        # kwargs the local path accepts. Honor `text` (and the legacy
        # `universal_newlines` alias) so callers can read decoded strings.
        text_mode = bool(
            kwargs.pop('text', False)
            or kwargs.pop('universal_newlines', False)
        )
        encoding = kwargs.pop('encoding', None) or 'utf-8'
        errors = kwargs.pop('errors', None) or 'replace'
        # The remaining kwargs (stdout/stderr PIPE, bufsize, etc.) are still
        # ignored on the remote path — paramiko channels handle their own
        # buffering — but we drain them out of kwargs so a future check can
        # warn if anything unexpected is left.
        kwargs.pop('stdout', None)
        kwargs.pop('stderr', None)
        kwargs.pop('bufsize', None)
        kwargs.pop('stdin', None)
        kwargs.pop('close_fds', None)

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
            if isinstance(line, bytes):
                line = line.decode(encoding, errors)
            remote_pid = line.strip()
            logger.info("Remote process started with PID: %s", remote_pid)
        except Exception as e:
            logger.warning("Failed to read remote PID: %s", e)
            remote_pid = None

        class _DecodingStream:
            """Decode paramiko channel output to str, with iterator support.

            The local subprocess.Popen path returns text-mode streams when
            callers pass `text=True`; this shim makes the remote path do the
            same so worker threads can `log.write(line)` without TypeError.
            """

            def __init__(self, raw, encoding, errors):
                self._raw = raw
                self._encoding = encoding
                self._errors = errors
                # Expose channel so callers can keep using existing
                # `proc.stdout.channel.exit_status_ready()` checks.
                self.channel = getattr(raw, 'channel', None)

            def _decode(self, chunk):
                if isinstance(chunk, bytes):
                    return chunk.decode(self._encoding, self._errors)
                return chunk

            def readline(self, *args, **kwargs):
                return self._decode(self._raw.readline(*args, **kwargs))

            def read(self, *args, **kwargs):
                return self._decode(self._raw.read(*args, **kwargs))

            def __iter__(self):
                while True:
                    line = self.readline()
                    if not line:
                        return
                    yield line

            def close(self):
                try:
                    self._raw.close()
                except Exception:
                    pass

        class RemoteProcess:
            def __init__(self, stdin, stdout, stderr, pid, executor, text_mode):
                self.stdin = stdin
                if text_mode:
                    self.stdout = _DecodingStream(stdout, encoding, errors)
                    self.stderr = _DecodingStream(stderr, encoding, errors)
                else:
                    self.stdout = stdout
                    self.stderr = stderr
                self.pid = pid
                self.executor = executor
                self.returncode = None
                self._buffer = ""

            @property
            def _channel(self):
                # When wrapped, fall through to the underlying channel.
                stdout = self.stdout
                channel = getattr(stdout, 'channel', None)
                return channel

            def poll(self):
                channel = self._channel
                if channel is not None and channel.exit_status_ready():
                    self.returncode = channel.recv_exit_status()
                    return self.returncode
                return None

            def wait(self, timeout=None):
                """Block until the remote process exits, honoring `timeout`.

                paramiko's recv_exit_status() has no timeout knob, so poll
                exit_status_ready() with a deadline. Raises
                subprocess.TimeoutExpired to mirror subprocess.Popen.wait.
                """
                channel = self._channel
                if channel is None:
                    self.returncode = -1
                    return self.returncode
                if timeout is None:
                    self.returncode = channel.recv_exit_status()
                    return self.returncode
                deadline = time.monotonic() + max(0.0, float(timeout))
                while True:
                    if channel.exit_status_ready():
                        self.returncode = channel.recv_exit_status()
                        return self.returncode
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(
                            cmd=str(self.pid), timeout=timeout
                        )
                    time.sleep(0.05)

            def terminate(self):
                if self.pid:
                    logger.info("Terminating remote process group %s", self.pid)
                    # We kill the process group (using negative PID) to ensure all children are killed
                    self.executor.run(['kill', '-TERM', f'-{self.pid}'])
                channel = self._channel
                if channel is not None:
                    try:
                        channel.close()
                    except Exception as exc:
                        logger.debug("RemoteProcess channel close failed: %s", exc)

            def kill(self):
                if self.pid:
                    logger.info("Killing remote process group %s", self.pid)
                    self.executor.run(['kill', '-9', f'-{self.pid}'])
                channel = self._channel
                if channel is not None:
                    try:
                        channel.close()
                    except Exception as exc:
                        logger.debug("RemoteProcess channel close failed: %s", exc)

        return RemoteProcess(stdin, stdout, stderr, remote_pid, self, text_mode)

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
        logger.debug("sync_from_remote: %s -> %s (local: %s)", remote_path, remote_path_mapped, local_path)

        # Check if remote path exists before getting
        res = self.run(['ls', '-d', remote_path_mapped], capture_output=True)
        if res.returncode != 0:
            logger.warning("Remote path %s does not exist, skipping sync_from_remote", remote_path_mapped)
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
            logger.error("SCP get failed: %s", e)

    def close(self):
        """Explicit cleanup for the underlying SSH connection.

        Prefer this over relying on `__del__`, which is not guaranteed to run
        during interpreter shutdown and can race against module teardown.
        """
        ssh = self.ssh
        self.ssh = None
        if ssh is not None:
            try:
                ssh.close()
            except Exception as exc:
                logger.debug("RemoteExecutor.close ssh.close failed: %s", exc)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
