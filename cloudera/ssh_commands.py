"""Commands we run on cluster machines over SSH.

Two monitoring tasks aren't available from the Cloudera Manager API at all, so
we log in to each machine over SSH and check directly:

    ping_host()       -> is the machine reachable, and how fast does it answer?
    get_disk_usage()  -> how full is each disk mount? (the `df` command)
    get_log_files()   -> how big is each log file? (the `find` command)

"Ping" here means opening an SSH connection and timing it: if the connection
succeeds the machine is reachable, and the connection time is the latency. We
deliberately don't shell out to the `ping` command — an SSH connection is
itself proof of reachability and needs no extra permissions.

All functions return plain dicts. Turning them into typed records happens in
data_sources/, so this file stays independent.
"""

import time

import paramiko


class SshConnectionError(Exception):
    """SSH genuinely failed (bad key, refused connection while running a
    command, ...). Note: ping_host() finding a machine unreachable is a normal
    result, not this error."""


class SshCommands:
    def __init__(self, username: str, key_path: str, port: int = 22, timeout: float = 10.0):
        self._username = username
        self._key_path = key_path
        self._port = port
        self._timeout = timeout

    def ping_host(self, hostname: str) -> dict:
        """Check reachability by opening (and timing) an SSH connection."""
        start = time.monotonic()
        try:
            connection = self._connect(hostname)
            latency_ms = (time.monotonic() - start) * 1000
            connection.close()
            return {"hostname": hostname, "reachable": True, "latency_ms": round(latency_ms, 2)}
        except (paramiko.SSHException, OSError):
            return {"hostname": hostname, "reachable": False, "latency_ms": None}

    def get_disk_usage(self, hostname: str, mounts: list[str]) -> list[dict]:
        """Run `df` and return how full each requested mount is (percent)."""
        connection = self._connect_or_raise(hostname)
        try:
            command = "df -P " + " ".join(mounts)
            _, stdout, stderr = connection.exec_command(command, timeout=self._timeout)
            output = stdout.read().decode()
            error = stderr.read().decode()
            if error and not output:
                raise SshConnectionError(f"df failed on {hostname}: {error}")
            return parse_df_output(hostname, output)
        finally:
            connection.close()

    def get_log_files(self, hostname: str, log_dirs: list[str]) -> list[dict]:
        """Run `find` in each log directory and return every file with its size."""
        connection = self._connect_or_raise(hostname)
        try:
            results: list[dict] = []
            for log_dir in log_dirs:
                command = f"find {log_dir} -type f -printf '%s %p\\n'"
                _, stdout, _ = connection.exec_command(command, timeout=self._timeout)
                results.extend(parse_find_output(hostname, stdout.read().decode()))
            return results
        finally:
            connection.close()

    # ---------- internals ----------

    def _connect(self, hostname: str) -> paramiko.SSHClient:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=hostname,
            port=self._port,
            username=self._username,
            key_filename=self._key_path,
            timeout=self._timeout,
        )
        return client

    def _connect_or_raise(self, hostname: str) -> paramiko.SSHClient:
        try:
            return self._connect(hostname)
        except (paramiko.SSHException, OSError) as exc:
            raise SshConnectionError(f"SSH connection to {hostname} failed: {exc}") from exc


def parse_df_output(hostname: str, output: str) -> list[dict]:
    """Turn `df -P` text output into dicts.

    Example input:
        Filesystem     1024-blocks     Used Available Capacity Mounted on
        /dev/sda1         51475068  9845296  39012345      21% /var
    """
    results = []
    for line in output.strip().splitlines()[1:]:  # first line is the header
        parts = line.split()
        if len(parts) < 6:
            continue
        try:
            used_percent = float(parts[4].rstrip("%"))
        except ValueError:
            continue
        results.append(
            {"hostname": hostname, "mount_point": parts[5], "used_percent": used_percent}
        )
    return results


def parse_find_output(hostname: str, output: str) -> list[dict]:
    """Turn `find -printf '%s %p'` output ("<bytes> <path>" per line) into dicts."""
    results = []
    for line in output.strip().splitlines():
        if not line.strip():
            continue
        size_str, _, path = line.partition(" ")
        try:
            size_bytes = int(size_str)
        except ValueError:
            continue
        results.append({"hostname": hostname, "path": path, "size_bytes": size_bytes})
    return results
