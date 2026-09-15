'''
This module provides a thread-safe SSH connection pool for remote access.
It wraps Paramiko SSH clients and Pexpect sessions to support:
- Non-interactive SSH command execution
- Interactive sessions with expect/send automation
- File uploads with automatic remote directory creation
- A pooled connection system to reuse and manage SSH connections efficiently
'''

import os
import socket
import threading
import time
import paramiko
import pexpect
import shlex
import boto3
from queue import Queue, Empty
from app.core.aws.ResourceConfigProvider import ResourceConfigProvider


class SSHConnectionProvider:
    _instance = None
    _lock = threading.Lock()

    def __init__(self):
        # Load SSH config basics (host, user, port) from AWSResourceConfigProvider
        ssh_config = ResourceConfigProvider.get_nvflare_ec2_ssh_config(check_cached=False)
        if ssh_config is None:
            raise RuntimeError("SSHConnectionProvider: No SSH config found")

        self.host = ssh_config.host
        self.username = ssh_config.username
        self.port = ssh_config.port or 22

        # Where we want the PEM written
        self.pem_path = ssh_config.private_key_path or "/app/keys/nvflare.pem"

        self.maxconnections = 5
        self.pool = Queue(maxsize=self.maxconnections)

        # Ensure key file exists before building pool
        self._ensure_key_file()

        self._build_initial_pool()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _ensure_key_file(self):
        """Fetch the SSH private key from Secrets Manager if not already written"""
        if os.path.exists(self.pem_path):
            return

        print(f"[SSHConnectionProvider] Fetching SSH key secret and writing to {self.pem_path}", flush=True)
        client = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "us-east-1"))
        response = client.get_secret_value(SecretId="nvflare/ssh_key")
        secret_string = response.get("SecretString")
        if not secret_string:
            raise RuntimeError("SSH private key secret is empty")

        os.makedirs(os.path.dirname(self.pem_path), exist_ok=True)
        with open(self.pem_path, "w") as f:
            f.write(secret_string)
        os.chmod(self.pem_path, 0o400)

    def _build_initial_pool(self):
        # Pre-populate pool with SSH connections
        for _ in range(self.maxconnections):
            self.pool.put(self._create_connection())

    def _create_connection(self):
        # Ensure key file exists before using it
        self._ensure_key_file()

        key = paramiko.RSAKey.from_private_key_file(self.pem_path)
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(
            self.host,
            username=self.username,
            pkey=key,
            port=self.port,
            timeout=30,
            banner_timeout=30,
            auth_timeout=30,
        )

        transport = c.get_transport()
        if transport is not None:
            transport.set_keepalive(30)

        return c

    def _is_connection_active(self, conn):
        if conn is None:
            return False
        try:
            transport = conn.get_transport()
            return bool(transport and transport.is_active() and transport.is_authenticated())
        except Exception:
            return False

    def _close_connection(self, conn):
        if conn is None:
            return
        try:
            conn.close()
        except Exception:
            pass

    def get_connection(self, timeout=5):
        # Retrieve a pooled connection or create a new one if pool is empty
        while True:
            try:
                conn = self.pool.get(timeout=timeout)
            except Empty:
                return self._create_connection()

            if self._is_connection_active(conn):
                return conn

            self._close_connection(conn)

    def release_connection(self, conn):
        # Return connection to pool, or close it if pool is full
        if not self._is_connection_active(conn):
            self._close_connection(conn)
            return

        try:
            self.pool.put(conn, block=False)
        except Exception:
            self._close_connection(conn)

    def rebuild_pool(self):
        # Destroy and rebuild all connections in the pool
        while not self.pool.empty():
            try:
                conn = self.pool.get_nowait()
                self._close_connection(conn)
            except Exception:
                pass
        self._build_initial_pool()

    def _run_once(self, command: str, timeout: int = 600):
        conn = None
        try:
            conn = self.get_connection()
            stdin, stdout, stderr = conn.exec_command(command, timeout=timeout)
            out = stdout.read().decode("utf-8", "ignore")
            err = stderr.read().decode("utf-8", "ignore")
            code = stdout.channel.recv_exit_status()
            return code, out, err
        finally:
            if conn is not None:
                self.release_connection(conn)

    def run(self, command: str, timeout: int = 600, retries: int = 2):
        # Run a non-interactive SSH command and return exit code, stdout, stderr
        last_error = None

        for attempt in range(retries + 1):
            try:
                return self._run_once(command, timeout=timeout)
            except (paramiko.SSHException, EOFError, OSError, socket.error) as e:
                last_error = e
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                return 1, "", f"SSH unavailable after reconnect attempts: {e}"

        return 1, "", f"SSH unavailable after reconnect attempts: {last_error}"

    def run_interactive(self, remote_cmd: str, expect_send_pairs: list, timeout: int = 60):
        # Run an interactive SSH session using pexpect and scripted inputs
        key_path = shlex.quote(self.pem_path)

        # Ensure a known_hosts file exists inside container
        known_hosts = "/app/known_hosts"
        try:
            os.makedirs(os.path.dirname(known_hosts), exist_ok=True)
            if not os.path.exists(known_hosts):
                open(known_hosts, "a").close()
        except Exception:
            known_hosts = "/dev/null"

        ssh_cmd = [
            "/usr/bin/ssh",
            "-tt",
            "-i", key_path,
            "-p", str(self.port),
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", f"UserKnownHostsFile={known_hosts}",
            "-o", "LogLevel=ERROR",
            f"{self.username}@{self.host}",
            remote_cmd,
        ]

        child = pexpect.spawn(ssh_cmd[0], ssh_cmd[1:], encoding="utf-8", timeout=timeout)

        full_output = ""
        try:
            for pattern, response in expect_send_pairs:
                child.expect(pattern)
                full_output += child.before
                full_output += child.after
                if response is not None:
                    child.sendline(response)

            try:
                while True:
                    full_output += child.read_nonblocking(65536, timeout=1)
            except Exception:
                pass
        finally:
            child.close()

        return full_output

    def _upload_once(self, local_path: str, remote_path: str):
        conn = None
        sftp = None
        try:
            conn = self.get_connection()
            sftp = conn.open_sftp()
            self._mkdirs(sftp, remote_path)
            sftp.put(local_path, remote_path)
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if conn is not None:
                self.release_connection(conn)

    def upload(self, local_path: str, remote_path: str, retries: int = 2):
        # Upload file to remote path via SFTP, creating directories if needed
        last_error = None

        for attempt in range(retries + 1):
            try:
                self._upload_once(local_path, remote_path)
                return
            except (paramiko.SSHException, EOFError, OSError, socket.error) as e:
                last_error = e
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                raise RuntimeError(f"SSH unavailable after reconnect attempts: {e}")

        raise RuntimeError(f"SSH unavailable after reconnect attempts: {last_error}")

    def _download_once(self, remote_path: str, local_path: str):
        conn = None
        sftp = None
        try:
            conn = self.get_connection()
            sftp = conn.open_sftp()
            sftp.get(remote_path, local_path)
        finally:
            if sftp is not None:
                try:
                    sftp.close()
                except Exception:
                    pass
            if conn is not None:
                self.release_connection(conn)

    def download(self, remote_path: str, local_path: str, retries: int = 2):
        # Download a remote file via SFTP into a local path.
        last_error = None

        for attempt in range(retries + 1):
            try:
                self._download_once(remote_path, local_path)
                return
            except (paramiko.SSHException, EOFError, OSError, socket.error) as e:
                last_error = e
                if attempt < retries:
                    time.sleep(min(2 ** attempt, 5))
                    continue
                raise RuntimeError(f"SSH unavailable after reconnect attempts: {e}") from e

        raise RuntimeError(f"SSH unavailable after reconnect attempts: {last_error}")

    def _mkdirs(self, sftp, remote_path: str):
        # Ensure all directories in the remote path exist
        dir_path = os.path.dirname(remote_path)
        parts = []
        for p in dir_path.strip("/").split("/"):
            parts.append(p)
            cur = "/" + "/".join(parts)
            try:
                sftp.stat(cur)
            except IOError:
                sftp.mkdir(cur)
