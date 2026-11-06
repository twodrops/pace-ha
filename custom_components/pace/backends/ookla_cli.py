"""Ookla Speedtest CLI backend implementation."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import platform
import shutil
import ssl
import tarfile
import tempfile
from typing import TYPE_CHECKING, Any
import urllib.request

import aiohttp

from ..const import (
    CLI_DOWNLOAD_MAX_RETRIES,
    CLI_DOWNLOAD_RETRY_DELAY,
    DEFAULT_SPEED_TEST_TIMEOUT,
    DOMAIN,
    LOGGER_NAME,
    MAX_SERVER_ID,
    MIN_SERVER_ID,
    OOKLA_ACCEPT_LICENSE_FLAGS,
    OOKLA_CLI_DOWNLOAD_BASE,
    OOKLA_CLI_VERSION,
    PROCESS_SUCCESS,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from ..exceptions import (
    CLIError,
    CLIExecutionError,
    CLINotFoundError,
    CLIOutputError,
    PaceError,
    SpeedTestTimeoutError,
)

_LOGGER = logging.getLogger(LOGGER_NAME)

# Ookla's naming convention for Linux architectures, see
# https://www.speedtest.net/apps/cli
_ARCH_MAP = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "aarch64",
    "arm64": "aarch64",
    "armv7l": "armhf",
    "armv7": "armhf",
    "armv6l": "armel",
    "arm": "armel",
    "i386": "i386",
    "i486": "i386",
    "i586": "i386",
    "i686": "i386",
}


class OoklaCLIBackend:
    """Ookla Speedtest CLI backend for speed testing.

    Wraps Ookla's official `speedtest` binary. Using this backend means
    accepting Ookla's license and GDPR terms on every invocation (handled
    automatically via --accept-license --accept-gdpr, same as the binary's
    own first-run prompt would require interactively).
    """

    def __init__(
        self,
        config_path: str,
        cli_path: str | None = None,
        hass: HomeAssistant | None = None,
    ):
        """Initialize the Ookla CLI backend."""
        self._config_path = config_path
        self._cli_path = cli_path
        self._platform_info: dict[str, str] | None = None
        self._hass = hass

    @property
    def cli_path(self) -> Path:
        """Get the CLI binary path."""
        if self._cli_path:
            return Path(self._cli_path)

        cli_dir = Path(self._config_path) / "custom_components/pace/bin/ookla"
        return cli_dir / "speedtest"

    def get_platform_info(self) -> dict[str, str]:
        """Get platform information for downloading the correct binary."""
        if self._platform_info:
            return self._platform_info

        machine = platform.machine().lower()
        arch = _ARCH_MAP.get(machine, machine)

        self._platform_info = {"system": "linux", "arch": arch}
        return self._platform_info

    def is_cli_supported(self) -> bool:
        """Check if the Ookla CLI has a build for this platform."""
        info = self.get_platform_info()
        return info["arch"] in {"x86_64", "aarch64", "armhf", "armel", "i386"}

    async def check_cli_exists(self) -> bool:
        """Check if the CLI binary exists and is executable."""
        cli_path = self.cli_path
        if not cli_path.exists():
            return False
        try:
            proc = await asyncio.create_subprocess_exec(
                str(cli_path),
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            return proc.returncode == PROCESS_SUCCESS
        except OSError as e:
            _LOGGER.debug("Ookla CLI check failed: %s", e)
            return False

    async def _accept_license(self) -> None:
        """Accept Ookla's license/GDPR terms (required before any real test)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                str(self.cli_path),
                *OOKLA_ACCEPT_LICENSE_FLAGS,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
        except OSError as e:
            _LOGGER.warning("Could not accept Ookla license: %s", e)

    async def download_cli(self) -> bool:
        """Download and install the Ookla CLI binary with retry logic."""
        if not self.is_cli_supported():
            _LOGGER.error(
                "Ookla CLI not supported on architecture: %s", platform.machine()
            )
            return False

        info = self.get_platform_info()
        url = (
            f"{OOKLA_CLI_DOWNLOAD_BASE}/"
            f"ookla-speedtest-{OOKLA_CLI_VERSION}-{info['system']}-{info['arch']}.tgz"
        )

        cli_dir = self.cli_path.parent
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, lambda _d=cli_dir: _d.mkdir(parents=True, exist_ok=True)
        )

        retry_delay = CLI_DOWNLOAD_RETRY_DELAY
        tmp_path = Path(tempfile.gettempdir()) / f"ookla_speedtest_{info['arch']}.tgz"

        for attempt in range(CLI_DOWNLOAD_MAX_RETRIES):
            try:
                if await self._download_archive(url, tmp_path):
                    await loop.run_in_executor(None, self._extract_and_install, tmp_path)
                    _LOGGER.info("Successfully downloaded and installed Ookla CLI")
                    return True
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
                _LOGGER.warning(
                    "Ookla CLI download attempt %d/%d failed: %s",
                    attempt + 1,
                    CLI_DOWNLOAD_MAX_RETRIES,
                    e,
                )
            except RuntimeError as e:
                _LOGGER.error("Ookla CLI install failed: %s", e)
                return False

            if attempt < CLI_DOWNLOAD_MAX_RETRIES - 1:
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30)

        return False

    async def _download_archive(self, url: str, dest: Path) -> bool:
        """Download the release archive, trying aiohttp then urllib."""
        try:
            timeout = aiohttp.ClientTimeout(total=90, connect=15)
            async with aiohttp.ClientSession(timeout=timeout) as session, session.get(
                url, headers={"User-Agent": "HomeAssistant-Pace"}
            ) as resp:
                if resp.status != 200:
                    raise aiohttp.ClientError(f"HTTP {resp.status} downloading {url}")
                data = await resp.read()
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, dest.write_bytes, data)
            return dest.exists() and dest.stat().st_size > 0
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.debug("aiohttp download failed, falling back to urllib: %s", e)

        def _urllib_download():
            req = urllib.request.Request(
                url, headers={"User-Agent": "HomeAssistant-Pace"}
            )
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, context=ctx, timeout=60) as resp, open(
                dest, "wb"
            ) as out:
                shutil.copyfileobj(resp, out)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _urllib_download)
        return dest.exists() and dest.stat().st_size > 0

    def _extract_and_install(self, tgz_path: Path) -> None:
        """Extract the tarball and install the `speedtest` binary (sync, runs in executor)."""
        import os as _os

        with tempfile.TemporaryDirectory() as extract_dir:
            with tarfile.open(tgz_path, "r:gz") as tar:
                if hasattr(tarfile, "data_filter"):
                    tar.extractall(extract_dir, filter="data")
                else:
                    tar.extractall(extract_dir)

            binary_path = None
            for root, _dirs, files in _os.walk(extract_dir):
                if "speedtest" in files:
                    binary_path = Path(root) / "speedtest"
                    break

            if binary_path is None:
                raise RuntimeError("Could not find 'speedtest' binary in the archive")

            self.cli_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(binary_path), str(self.cli_path))
            self.cli_path.chmod(0o755)
        try:
            tgz_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def ensure_cli_available(self, force_download: bool = False) -> bool:
        """Ensure the Ookla CLI is available, downloading if necessary."""
        if not force_download and await self.check_cli_exists():
            await self._accept_license()
            if self._hass:
                from homeassistant.helpers import issue_registry as ir

                ir.async_delete_issue(self._hass, DOMAIN, "cli_download_failed")
            return True

        _LOGGER.info("Ookla CLI not found, attempting to download...")
        success = await self.download_cli()

        if success:
            await self._accept_license()
            if self._hass:
                from homeassistant.helpers import issue_registry as ir

                ir.async_delete_issue(self._hass, DOMAIN, "cli_download_failed")
            return True

        if self._hass:
            from homeassistant.helpers import issue_registry as ir

            ir.async_create_issue(
                self._hass,
                DOMAIN,
                "cli_download_failed",
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="cli_download_failed",
            )
        return False

    async def run_speed_test(
        self,
        server_id: int | None = None,
        custom_server: str | None = None,
        skip_cert_verify: bool = False,  # noqa: ARG002 - Ookla CLI has no equivalent flag
        timeout: int = DEFAULT_SPEED_TEST_TIMEOUT,
        source_interface: str | None = None,
        source_ip: str | None = None,
    ) -> dict[str, Any]:
        """Run speed test using the Ookla CLI and return the unified result dict."""
        if not self.cli_path.exists():
            _LOGGER.error("Ookla CLI binary not found at %s", self.cli_path)
            raise CLINotFoundError(
                translation_domain=DOMAIN, translation_key="cli_not_available"
            )

        if custom_server:
            _LOGGER.warning(
                "Ookla backend has no custom-server support; ignoring custom_server=%s",
                custom_server,
            )

        cmd = [str(self.cli_path), *OOKLA_ACCEPT_LICENSE_FLAGS, "--format=json"]

        if server_id is not None:
            if (
                not isinstance(server_id, int)
                or server_id < MIN_SERVER_ID
                or server_id > MAX_SERVER_ID
            ):
                raise PaceError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_configuration",
                )
            cmd.extend(["-s", str(server_id)])

        if source_interface:
            cmd.extend(["--interface", source_interface])
        if source_ip:
            cmd.extend(["--ip", source_ip])

        _LOGGER.info("Running Ookla CLI with command: %s", " ".join(cmd))

        try:
            async with asyncio.timeout(timeout):
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await proc.communicate()

                if proc.returncode != PROCESS_SUCCESS:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    _LOGGER.error(
                        "Ookla CLI failed with code %d: %s", proc.returncode, error_msg
                    )
                    raise CLIExecutionError(
                        translation_domain=DOMAIN,
                        translation_key="speed_test_failed",
                        translation_placeholders={"error": error_msg},
                    )

                result = json.loads(stdout.decode())
                return self._parse_raw_result(result, server_id)

        except asyncio.TimeoutError as e:
            _LOGGER.error("Ookla speed test timed out")
            raise SpeedTestTimeoutError(
                translation_domain=DOMAIN,
                translation_key="timeout_error",
                translation_placeholders={"timeout": str(timeout)},
            ) from e
        except json.JSONDecodeError as e:
            _LOGGER.error("Failed to parse Ookla CLI output: %s", e)
            raise CLIOutputError(
                translation_domain=DOMAIN,
                translation_key="speed_test_failed",
                translation_placeholders={"error": str(e)},
            ) from e
        except CLIError:
            raise
        except OSError as e:
            _LOGGER.error("Ookla speed test process error: %s", e)
            raise CLIExecutionError(
                translation_domain=DOMAIN,
                translation_key="speed_test_failed",
                translation_placeholders={"error": str(e)},
            ) from e

    @staticmethod
    def _parse_raw_result(result: dict[str, Any], server_id: int | None) -> dict[str, Any]:
        """Map Ookla's raw --format=json output to the unified result dict shape."""
        ping = result.get("ping", {})
        download = result.get("download", {})
        upload = result.get("upload", {})
        server = result.get("server", {})

        timestamp_str = result.get("timestamp")
        try:
            timestamp = (
                datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                if timestamp_str
                else datetime.now(timezone.utc)
            )
        except ValueError:
            timestamp = datetime.now(timezone.utc)

        return {
            "download": round(download.get("bandwidth", 0) * 8 / 1_000_000, 2),
            "upload": round(upload.get("bandwidth", 0) * 8 / 1_000_000, 2),
            "ping": round(ping.get("latency", 0), 2),
            "jitter": round(ping.get("jitter", 0), 2),
            "server": {
                "id": server_id or server.get("id"),
                "name": server.get("name", "Unknown"),
                # Ookla's raw "location"/"country" are city/country only, no
                # separate sponsor field - the operator is "name" (e.g. "Deutsche
                # Telekom"), confirmed via a live run against the real CLI.
                "location": ", ".join(
                    filter(None, [server.get("location"), server.get("country")])
                )
                or "Unknown",
                "sponsor": server.get("name", "Unknown"),
            },
            "timestamp": timestamp,
            # Raw per-phase byte counters - needed for lifetime data tracking.
            "bytes_sent": upload.get("bytes", 0),
            "bytes_received": download.get("bytes", 0),
        }
