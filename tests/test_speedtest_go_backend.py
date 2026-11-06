"""Tests for the speedtest-go CLI backend."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.pace.backends.speedtest_go_cli import (
    SpeedtestGoCLIBackend,
)
from custom_components.pace.exceptions import (
    CLINotFoundError,
    CLIOutputError,
    PaceError,
)

# ---- Platform info ----


def test_get_platform_info_amd64() -> None:
    """Test platform info for x86_64 maps to speedtest-go's naming."""
    cli = SpeedtestGoCLIBackend("/fake/path")
    with patch(
        "custom_components.pace.backends.speedtest_go_cli.platform"
    ) as mock_plat:
        mock_plat.machine.return_value = "x86_64"
        info = cli.get_platform_info()
    assert info["arch"] == "x86_64"
    assert info["system"] == "Linux"


def test_get_platform_info_aarch64_maps_to_arm64() -> None:
    """Test aarch64 maps to speedtest-go's 'arm64' naming (not 'aarch64')."""
    cli = SpeedtestGoCLIBackend("/fake/path")
    with patch(
        "custom_components.pace.backends.speedtest_go_cli.platform"
    ) as mock_plat:
        mock_plat.machine.return_value = "aarch64"
        info = cli.get_platform_info()
    assert info["arch"] == "arm64"


# ---- is_cli_supported ----


def test_is_cli_supported_arm64() -> None:
    """Test CLI is supported on arm64."""
    cli = SpeedtestGoCLIBackend("/fake/path")
    with patch(
        "custom_components.pace.backends.speedtest_go_cli.platform"
    ) as mock_plat:
        mock_plat.machine.return_value = "arm64"
        assert cli.is_cli_supported() is True


def test_is_cli_supported_unsupported() -> None:
    """Test CLI is not supported on an unknown architecture."""
    cli = SpeedtestGoCLIBackend("/fake/path")
    with patch(
        "custom_components.pace.backends.speedtest_go_cli.platform"
    ) as mock_plat:
        mock_plat.machine.return_value = "sparc64"
        assert cli.is_cli_supported() is False


# ---- cli_path ----


def test_cli_path_default() -> None:
    """Test default cli_path is namespaced under bin/speedtest_go/."""
    cli = SpeedtestGoCLIBackend("/config")
    assert cli.cli_path == Path(
        "/config/custom_components/pace/bin/speedtest_go/speedtest-go"
    )


# ---- run_speed_test ----


async def test_run_speed_test_missing_binary() -> None:
    """Test run_speed_test raises CLINotFoundError when binary is missing."""
    cli = SpeedtestGoCLIBackend("/config", cli_path="/nonexistent/speedtest-go")
    with pytest.raises(CLINotFoundError):
        await cli.run_speed_test()


async def test_run_speed_test_invalid_server_id(tmp_path) -> None:
    """Test run_speed_test rejects an out-of-range server_id."""
    binary = tmp_path / "speedtest-go"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = SpeedtestGoCLIBackend("/config", cli_path=str(binary))
    with pytest.raises(PaceError):
        await cli.run_speed_test(server_id=99999)


async def test_run_speed_test_parses_real_dict_wrapped_output(tmp_path) -> None:
    """Regression test: real --json output is {"servers": [...]}, not a bare list.

    A past bug assumed a bare array and indexed results[0], raising a
    KeyError on every real run (confirmed via a live runtime test against
    the actual binary) - the speed test always failed after fully running.
    """
    binary = tmp_path / "speedtest-go"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = SpeedtestGoCLIBackend("/config", cli_path=str(binary))

    raw_result = {
        "timestamp": "2026-11-06 08:18:47.480",
        "user_info": {"IP": "1.2.3.4", "Isp": "Example ISP"},
        "servers": [
            {
                "id": "1584",
                "name": "Munchen",
                "country": "Germany",
                "sponsor": "1&1 Mobilfunk",
                "latency": 20_000_000,
                "jitter": 1_800_000,
                "dl_speed": 11_882_500.0,
                "ul_speed": 4_185_000.0,
                "test_duration": {"download": 10_000_000_000, "upload": 10_000_000_000},
            }
        ],
    }

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(
        return_value=(json.dumps(raw_result).encode(), b"")
    )
    mock_proc.returncode = 0

    with patch(
        "custom_components.pace.backends.speedtest_go_cli.asyncio.create_subprocess_exec",
        AsyncMock(return_value=mock_proc),
    ):
        result = await cli.run_speed_test()

    assert result["server"]["name"] == "Munchen"
    assert result["download"] == pytest.approx(95.06, rel=0.01)


async def test_run_speed_test_empty_servers_list_raises(tmp_path) -> None:
    """Test an empty servers list in the real dict-wrapped shape raises cleanly."""
    binary = tmp_path / "speedtest-go"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = SpeedtestGoCLIBackend("/config", cli_path=str(binary))

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(
        return_value=(json.dumps({"servers": []}).encode(), b"")
    )
    mock_proc.returncode = 0

    with (
        patch(
            "custom_components.pace.backends.speedtest_go_cli.asyncio.create_subprocess_exec",
            AsyncMock(return_value=mock_proc),
        ),
        pytest.raises(CLIOutputError),
    ):
        await cli.run_speed_test()


async def test_run_speed_test_custom_url(tmp_path) -> None:
    """Test run_speed_test uses --custom-url when custom_server is given."""
    binary = tmp_path / "speedtest-go"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = SpeedtestGoCLIBackend("/config", cli_path=str(binary))

    # Raw --json output: {"servers": [...], "user_info": {...}, ...} - confirmed
    # against a real `speedtest-go --json` run (dl_speed/ul_speed in bytes/sec,
    # latency/jitter/test_duration in nanoseconds).
    raw_result = {
        "servers": [
            {
                "id": "7",
                "name": "Example Server",
                "country": "US",
                "sponsor": "Example Sponsor",
                "latency": 15_000_000,  # 15ms
                "jitter": 2_000_000,  # 2ms
                "dl_speed": 12_500_000.0,  # 100 Mbps in bytes/sec
                "ul_speed": 6_250_000.0,  # 50 Mbps in bytes/sec
                "test_duration": {"download": 10_000_000_000, "upload": 10_000_000_000},
            }
        ]
    }

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(
        return_value=(json.dumps(raw_result).encode(), b"")
    )
    mock_proc.returncode = 0

    with patch(
        "custom_components.pace.backends.speedtest_go_cli.asyncio.create_subprocess_exec",
        AsyncMock(return_value=mock_proc),
    ) as mock_exec:
        result = await cli.run_speed_test(custom_server="https://speedtest.example.com/")

    called_cmd = mock_exec.call_args[0]
    assert "--custom-url" in called_cmd
    assert "https://speedtest.example.com/" in called_cmd

    assert result["download"] == pytest.approx(100.0, rel=0.01)
    assert result["upload"] == pytest.approx(50.0, rel=0.01)
    assert result["ping"] == 15.0
    assert result["jitter"] == 2.0
    assert result["server"]["name"] == "Example Server"
    # bytes = rate(bytes/sec) * duration(sec) = 12_500_000 * 10 = 125,000,000
    assert result["bytes_received"] == 125_000_000
    assert result["bytes_sent"] == 62_500_000


async def test_run_speed_test_with_source_interface(tmp_path) -> None:
    """Test --source is passed when source_interface is given."""
    binary = tmp_path / "speedtest-go"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = SpeedtestGoCLIBackend("/config", cli_path=str(binary))

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
    mock_proc.returncode = 0

    with patch(
        "custom_components.pace.backends.speedtest_go_cli.asyncio.create_subprocess_exec",
        AsyncMock(return_value=mock_proc),
    ) as mock_exec:
        with pytest.raises(Exception):
            # Empty "[]" result triggers a parsing error downstream, but we
            # only care about the command that was built here.
            await cli.run_speed_test(source_interface="eth0")

    called_cmd = list(mock_exec.call_args[0])
    assert "--source" in called_cmd
    assert called_cmd[called_cmd.index("--source") + 1] == "eth0"


async def test_run_speed_test_with_source_ip_fallback(tmp_path) -> None:
    """Test --source is passed with the IP when no interface is given."""
    binary = tmp_path / "speedtest-go"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = SpeedtestGoCLIBackend("/config", cli_path=str(binary))

    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"[]", b""))
    mock_proc.returncode = 0

    with patch(
        "custom_components.pace.backends.speedtest_go_cli.asyncio.create_subprocess_exec",
        AsyncMock(return_value=mock_proc),
    ) as mock_exec:
        with pytest.raises(Exception):
            await cli.run_speed_test(source_ip="10.20.0.101")

    called_cmd = list(mock_exec.call_args[0])
    assert "--source" in called_cmd
    assert called_cmd[called_cmd.index("--source") + 1] == "10.20.0.101"
