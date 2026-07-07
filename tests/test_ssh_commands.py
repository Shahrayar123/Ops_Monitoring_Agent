"""Tests for the SSH command helpers, with paramiko fully faked — there are no
real machines to SSH into yet."""

from unittest.mock import MagicMock, patch

import pytest

from cloudera import SshCommands, SshConnectionError
from cloudera.ssh_commands import parse_df_output, parse_find_output


def _fake_exec_command(stdout_text: str, stderr_text: str = ""):
    stdout = MagicMock()
    stdout.read.return_value = stdout_text.encode()
    stderr = MagicMock()
    stderr.read.return_value = stderr_text.encode()
    return MagicMock(return_value=(MagicMock(), stdout, stderr))


def test_df_output_is_parsed_into_dicts():
    output = (
        "Filesystem     1024-blocks     Used Available Capacity Mounted on\n"
        "/dev/sda1         51475068  9845296  39012345      21% /var\n"
        "/dev/sda2         20000000 18000000   1000000      95% /opt\n"
    )
    assert parse_df_output("node1", output) == [
        {"hostname": "node1", "mount_point": "/var", "used_percent": 21.0},
        {"hostname": "node1", "mount_point": "/opt", "used_percent": 95.0},
    ]


def test_find_output_is_parsed_into_dicts():
    output = (
        "314572800 /var/log/hadoop-hdfs/hadoop-hdfs-namenode.log\n"
        "1288490188 /var/log/hadoop-hdfs/hadoop-hdfs-datanode.log\n"
    )
    assert parse_find_output("node2", output) == [
        {
            "hostname": "node2",
            "path": "/var/log/hadoop-hdfs/hadoop-hdfs-namenode.log",
            "size_bytes": 314572800,
        },
        {
            "hostname": "node2",
            "path": "/var/log/hadoop-hdfs/hadoop-hdfs-datanode.log",
            "size_bytes": 1288490188,
        },
    ]


@patch.object(SshCommands, "_connect")
def test_ping_reports_reachable_with_latency(mock_connect):
    mock_connect.return_value = MagicMock()

    result = SshCommands(username="u", key_path="/fake/key").ping_host("node1.internal")

    assert result["hostname"] == "node1.internal"
    assert result["reachable"] is True
    assert result["latency_ms"] is not None


@patch.object(SshCommands, "_connect", side_effect=OSError("connection refused"))
def test_ping_reports_unreachable_without_raising(mock_connect):
    result = SshCommands(username="u", key_path="/fake/key").ping_host("node3.internal")

    assert result == {"hostname": "node3.internal", "reachable": False, "latency_ms": None}


@patch.object(SshCommands, "_connect")
def test_disk_usage_runs_df_and_parses_it(mock_connect):
    connection = MagicMock()
    connection.exec_command = _fake_exec_command(
        "Filesystem     1024-blocks     Used Available Capacity Mounted on\n"
        "/dev/sda1         51475068  9845296  39012345      56% /var\n"
    )
    mock_connect.return_value = connection

    results = SshCommands(username="u", key_path="/fake/key").get_disk_usage(
        "node1.internal", ["/var"]
    )

    assert results == [
        {"hostname": "node1.internal", "mount_point": "/var", "used_percent": 56.0}
    ]
    connection.close.assert_called_once()


@patch.object(SshCommands, "_connect", side_effect=OSError("connection refused"))
def test_disk_usage_raises_when_ssh_fails(mock_connect):
    with pytest.raises(SshConnectionError):
        SshCommands(username="u", key_path="/fake/key").get_disk_usage("node3.internal", ["/var"])
