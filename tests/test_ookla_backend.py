"""Tests for the Ookla CLI backend."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.pace.backends.ookla_cli import OoklaCLIBackend
from custom_components.pace.exceptions import (
    CLINotFoundError,
    PaceError,
)

# ---- Platform info ----


def test_get_platform_info_x86_64() -> None:
    """Test platform info for x86_64."""
    cli = OoklaCLIBackend("/fake/path")
    with patch("custom_components.pace.backends.ookla_cli.platform") as mock_plat:
        mock_plat.machine.return_value = "x86_64"
        info = cli.get_platform_info()
    assert info["arch"] == "x86_64"
    assert info["system"] == "linux"


def test_get_platform_info_armv7() -> None:
    """Test platform info for 32-bit ARM (armv7l)."""
    cli = OoklaCLIBackend("/fake/path")
    with patch("custom_components.pace.backends.ookla_cli.platform") as mock_plat:
        mock_plat.machine.return_value = "armv7l"
        info = cli.get_platform_info()
    assert info["arch"] == "armhf"


# ---- is_cli_supported ----


def test_is_cli_supported_aarch64() -> None:
    """Test CLI is supported on aarch64 (broader arch support than LibreSpeed)."""
    cli = OoklaCLIBackend("/fake/path")
    with patch("custom_components.pace.backends.ookla_cli.platform") as mock_plat:
        mock_plat.machine.return_value = "aarch64"
        assert cli.is_cli_supported() is True


def test_is_cli_supported_unsupported() -> None:
    """Test CLI is not supported on an unknown architecture."""
    cli = OoklaCLIBackend("/fake/path")
    with patch("custom_components.pace.backends.ookla_cli.platform") as mock_plat:
        mock_plat.machine.return_value = "sparc64"
        assert cli.is_cli_supported() is False


# ---- cli_path ----


def test_cli_path_default() -> None:
    """Test default cli_path is namespaced under bin/ookla/."""
    cli = OoklaCLIBackend("/config")
    assert cli.cli_path == Path(
        "/config/custom_components/pace/bin/ookla/speedtest"
    )


def test_cli_path_custom() -> None:
    """Test custom cli_path."""
    cli = OoklaCLIBackend("/config", cli_path="/usr/local/bin/speedtest")
    assert cli.cli_path == Path("/usr/local/bin/speedtest")


# ---- run_speed_test ----


async def test_run_speed_test_missing_binary() -> None:
    """Test run_speed_test raises CLINotFoundError when binary is missing."""
    cli = OoklaCLIBackend("/config", cli_path="/nonexistent/speedtest")
    with pytest.raises(CLINotFoundError):
        await cli.run_speed_test()


async def test_run_speed_test_invalid_server_id(tmp_path) -> None:
    """Test run_speed_test rejects an out-of-range server_id."""
    binary = tmp_path / "speedtest"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = OoklaCLIBackend("/config", cli_path=str(binary))
    with pytest.raises(PaceError):
        await cli.run_speed_test(server_id=99999)


async def test_run_speed_test_ignores_custom_server(tmp_path, caplog) -> None:
    """Test run_speed_test logs a warning and ignores custom_server (Ookla has none)."""
    binary = tmp_path / "speedtest"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = OoklaCLIBackend("/config", cli_path=str(binary))

    with patch(
        "custom_components.pace.backends.ookla_cli.asyncio.create_subprocess_exec",
        AsyncMock(
            return_value=AsyncMock(
                communicate=AsyncMock(
                    return_value=(
                        b'{"ping": {"latency": 10.5, "jitter": 1.2}, '
                        b'"download": {"bandwidth": 12500000, "bytes": 50000000}, '
                        b'"upload": {"bandwidth": 6250000, "bytes": 25000000}, '
                        b'"server": {"id": 1, "name": "Test", "location": "City", "country": "US"}}',
                        b"",
                    )
                ),
                returncode=0,
            )
        ),
    ):
        result = await cli.run_speed_test(custom_server="https://example.com")

    assert "ignoring custom_server" in caplog.text
    assert result["download"] == pytest.approx(100.0, rel=0.01)  # 12.5MB/s * 8 / 1e6
    assert result["upload"] == pytest.approx(50.0, rel=0.01)
    assert result["ping"] == 10.5
    assert result["jitter"] == 1.2
    assert result["bytes_sent"] == 25000000
    assert result["bytes_received"] == 50000000
    assert result["server"]["name"] == "Test"


async def test_run_speed_test_with_source_interface_and_ip(tmp_path) -> None:
    """Test --interface and --ip are both passed when both are configured."""
    binary = tmp_path / "speedtest"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    cli = OoklaCLIBackend("/config", cli_path=str(binary))

    mock_exec = AsyncMock(
        return_value=AsyncMock(
            communicate=AsyncMock(
                return_value=(
                    b'{"ping": {"latency": 10.5, "jitter": 1.2}, '
                    b'"download": {"bandwidth": 12500000, "bytes": 50000000}, '
                    b'"upload": {"bandwidth": 6250000, "bytes": 25000000}, '
                    b'"server": {"id": 1, "name": "Test", "location": "City", "country": "US"}}',
                    b"",
                )
            ),
            returncode=0,
        )
    )
    with patch(
        "custom_components.pace.backends.ookla_cli.asyncio.create_subprocess_exec",
        mock_exec,
    ):
        await cli.run_speed_test(source_interface="eth0", source_ip="10.20.0.101")

    call_args = list(mock_exec.call_args[0])
    assert "--interface" in call_args
    assert call_args[call_args.index("--interface") + 1] == "eth0"
    assert "--ip" in call_args
    assert call_args[call_args.index("--ip") + 1] == "10.20.0.101"
