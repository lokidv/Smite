"""Thin synchronous SSH/SFTP helper built on paramiko.

paramiko is blocking, so callers run these helpers inside ``asyncio.to_thread``.
A single :class:`SSHSession` keeps one TCP connection open for the whole
provisioning job (command execution + file uploads).
"""
from __future__ import annotations

import posixpath
import socket
import time
from typing import Callable, Optional

try:
    import paramiko
except ImportError:  # pragma: no cover - keeps the panel bootable without the dep
    paramiko = None  # type: ignore[assignment]

OutputCallback = Callable[[str], None]


class SSHError(Exception):
    """Raised when the SSH connection or an operation fails."""


class SSHSession:
    """A reusable SSH connection to a single target host."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 22,
        connect_timeout: float = 30.0,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.connect_timeout = connect_timeout
        self._client: Optional[paramiko.SSHClient] = None
        self._sftp: Optional[paramiko.SFTPClient] = None

    # -- lifecycle ---------------------------------------------------------
    def connect(self) -> None:
        if paramiko is None:
            raise SSHError(
                "The 'paramiko' package is not installed on the panel. "
                "Rebuild/update the panel (pip install -r requirements.txt) to use remote provisioning."
            )
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=self.connect_timeout,
                banner_timeout=self.connect_timeout,
                auth_timeout=self.connect_timeout,
                allow_agent=False,
                look_for_keys=False,
            )
        except Exception as exc:  # noqa: BLE001 - surface a clean message
            raise SSHError(f"SSH connection to {self.host}:{self.port} failed: {exc}") from exc
        self._client = client

    def close(self) -> None:
        if self._sftp is not None:
            try:
                self._sftp.close()
            except Exception:  # noqa: BLE001
                pass
            self._sftp = None
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    def __enter__(self) -> "SSHSession":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- commands ----------------------------------------------------------
    def run(
        self,
        command: str,
        timeout: float = 1800.0,
        on_output: Optional[OutputCallback] = None,
        get_pty: bool = False,
    ) -> tuple[int, str]:
        """Run a command, streaming combined stdout/stderr to ``on_output``.

        Returns ``(exit_code, combined_output)``. Raises :class:`SSHError`
        if the command does not finish within ``timeout`` seconds.
        """
        if self._client is None:
            raise SSHError("SSH session is not connected")

        transport = self._client.get_transport()
        if transport is None:
            raise SSHError("SSH transport unavailable")

        channel = transport.open_session(timeout=self.connect_timeout)
        if get_pty:
            channel.get_pty()
        channel.settimeout(5.0)
        channel.set_combine_stderr(True)
        channel.exec_command(command)

        collected: list[str] = []
        buffer = b""
        deadline = time.time() + timeout
        timed_out = False

        def drain_ready() -> bool:
            nonlocal buffer
            got_data = False
            while channel.recv_ready():
                chunk = channel.recv(65536)
                if not chunk:
                    break
                got_data = True
                buffer += chunk
                buffer = self._emit_lines(buffer, collected, on_output)
            return got_data

        while True:
            got_data = drain_ready()
            if channel.exit_status_ready() and not channel.recv_ready():
                break
            if time.time() > deadline:
                timed_out = True
                break
            if not got_data:
                time.sleep(0.05)

        if not timed_out:
            # Drain whatever is left until EOF (the process already exited).
            while True:
                try:
                    chunk = channel.recv(65536)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buffer += chunk
                buffer = self._emit_lines(buffer, collected, on_output)

        if buffer:
            text = buffer.decode("utf-8", "replace")
            collected.append(text)
            if on_output:
                on_output(text)

        if timed_out:
            try:
                channel.close()
            except Exception:  # noqa: BLE001
                pass
            raise SSHError(f"remote command timed out after {int(timeout)} seconds")

        exit_code = channel.recv_exit_status()
        channel.close()
        return exit_code, "".join(collected)

    @staticmethod
    def _emit_lines(buffer: bytes, collected: list[str], on_output: Optional[OutputCallback]) -> bytes:
        while b"\n" in buffer:
            line, buffer = buffer.split(b"\n", 1)
            text = line.decode("utf-8", "replace")
            collected.append(text + "\n")
            if on_output:
                on_output(text)
        return buffer

    # -- file transfer -----------------------------------------------------
    def _ensure_sftp(self) -> paramiko.SFTPClient:
        if self._client is None:
            raise SSHError("SSH session is not connected")
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
        return self._sftp

    def put_file(self, local_path: str, remote_path: str) -> int:
        """Upload a local file; returns the uploaded size in bytes."""
        sftp = self._ensure_sftp()
        self._mkdir_p(posixpath.dirname(remote_path))
        try:
            sftp.put(local_path, remote_path)
            return sftp.stat(remote_path).st_size or 0
        except Exception as exc:  # noqa: BLE001
            raise SSHError(f"Failed to upload {local_path} -> {remote_path}: {exc}") from exc

    def put_text(self, content: str, remote_path: str, mode: int = 0o644) -> None:
        """Write text content to a remote file."""
        sftp = self._ensure_sftp()
        self._mkdir_p(posixpath.dirname(remote_path))
        try:
            with sftp.open(remote_path, "w") as fh:
                fh.write(content)
            sftp.chmod(remote_path, mode)
        except Exception as exc:  # noqa: BLE001
            raise SSHError(f"Failed to write {remote_path}: {exc}") from exc

    def _mkdir_p(self, remote_dir: str) -> None:
        if not remote_dir or remote_dir in ("/", "."):
            return
        sftp = self._ensure_sftp()
        parts = remote_dir.strip("/").split("/")
        current = ""
        for part in parts:
            current = f"{current}/{part}" if current else f"/{part}"
            try:
                sftp.stat(current)
            except IOError:
                try:
                    sftp.mkdir(current)
                except IOError:
                    # Race or permission issue; let later operations surface it.
                    pass
