"""speedtest-go CLI backend implementation (github.com/showwin/speedtest-go)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import logging
from pathlib import Path
import platform
import tarfile
import tempfile
from typing import TYPE_CHECKING, Any

import aiohttp

from ..const import (
    CLI_DOWNLOAD_MAX_RETRIES,
    CLI_DOWNLOAD_RETRY_DELAY,
    CLI_DOWNLOAD_TIMEOUT_CONNECT,
    CLI_DOWNLOAD_TIMEOUT_READ,
    CLI_DOWNLOAD_TIMEOUT_TOTAL,
    DEFAULT_SPEED_TEST_TIMEOUT,
    DOMAIN,
    HTTP_OK,
    LOGGER_NAME,
    MAX_HOSTNAME_LENGTH,
    MAX_SERVER_ID,
    MIN_SERVER_ID,
    PROCESS_SUCCESS,
    SPEEDTEST_GO_GITHUB_REPO,
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

# goreleaser's default Linux architecture naming used by speedtest-go releases.
_ARCH_MAP = {
    "x86_64": "x86_64",
    "amd64": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armv7",
    "armv6l": "armv6",
    "i386": "i386",
    "i686": "i386",
}


class SpeedtestGoCLIBackend:
    """speedtest-go CLI backend for speed testing.

    Wraps the open-source `speedtest-go` binary - an MIT-licensed, clean-room
    client for the same speedtest.net/Ookla server network, with no
    proprietary binary or license/GDPR acceptance requirement.
    """

    def __init__(
        self,
        config_path: str,
        cli_path: str | None = None,
        hass: HomeAssistant | None = None,
    ):
        """Initialize the speedtest-go CLI backend."""
        self._config_path = config_path
        self._cli_path = cli_path
        self._platform_info: dict[str, str] | None = None
        self._hass = hass

    @property
    def cli_path(self) -> Path:
        """Get the CLI binary path."""
        if self._cli_path:
            return Path(self._cli_path)

        cli_dir = (
            Path(self._config_path) / "custom_components/pace/bin/speedtest_go"
        )
        return cli_dir / "speedtest-go"

    def get_platform_info(self) -> dict[str, str]:
        """Get platform information for downloading the correct binary."""
        if self._platform_info:
            return self._platform_info

        machine = platform.machine().lower()
        arch = _ARCH_MAP.get(machine, machine)

        self._platform_info = {"system": "Linux", "arch": arch, "extension": ".tar.gz"}
        return self._platform_info

    def is_cli_supported(self) -> bool:
        """Check if speedtest-go has a build for this platform."""
        info = self.get_platform_info()
        return info["arch"] in {"x86_64", "arm64", "armv7", "armv6", "i386"}

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
            _LOGGER.debug("speedtest-go CLI check failed: %s", e)
            return False

    async def download_cli(self) -> bool:
        """Download and install the speedtest-go binary with retry logic."""
        if not self.is_cli_supported():
            _LOGGER.error(
                "speedtest-go not supported on architecture: %s", platform.machine()
            )
            return False

        info = self.get_platform_info()
        max_retries = CLI_DOWNLOAD_MAX_RETRIES
        retry_delay = CLI_DOWNLOAD_RETRY_DELAY

        for attempt in range(max_retries):
            try:
                timeout = aiohttp.ClientTimeout(
                    total=CLI_DOWNLOAD_TIMEOUT_TOTAL,
                    connect=CLI_DOWNLOAD_TIMEOUT_CONNECT,
                    sock_read=CLI_DOWNLOAD_TIMEOUT_READ,
                )
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    _LOGGER.info(
                        "Fetching speedtest-go release info (attempt %d/%d)...",
                        attempt + 1,
                        max_retries,
                    )
                    async with session.get(
                        f"https://api.github.com/repos/{SPEEDTEST_GO_GITHUB_REPO}/releases/latest",
                        headers={"Accept": "application/vnd.github.v3+json"},
                    ) as resp:
                        if resp.status != HTTP_OK:
                            _LOGGER.error(
                                "Failed to get latest release info: %s", resp.status
                            )
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue
                            return False
                        release_data = await resp.json()
                        version = release_data["tag_name"].lstrip("v")

                    asset_name = (
                        f"speedtest-go_{version}_{info['system']}_{info['arch']}"
                        f"{info['extension']}"
                    )

                    asset_url = None
                    checksums_url = None
                    for asset in release_data["assets"]:
                        if asset["name"] == asset_name:
                            asset_url = asset["browser_download_url"]
                        elif asset["name"] == "checksums.txt":
                            checksums_url = asset["browser_download_url"]

                    if not asset_url:
                        _LOGGER.error(
                            "No speedtest-go binary found for %s %s",
                            info["system"],
                            info["arch"],
                        )
                        return False

                    expected_checksum = await self._fetch_expected_checksum(
                        session, checksums_url, asset_name
                    )

                    _LOGGER.info(
                        "Downloading speedtest-go binary (%s)...", asset_name
                    )
                    async with session.get(asset_url, allow_redirects=True) as resp:
                        if resp.status != HTTP_OK:
                            _LOGGER.error(
                                "Failed to download speedtest-go binary: HTTP %s",
                                resp.status,
                            )
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue
                            return False
                        data = await resp.read()

                    if expected_checksum:
                        actual_checksum = hashlib.sha256(data).hexdigest().lower()
                        if actual_checksum != expected_checksum:
                            _LOGGER.error(
                                "Checksum validation failed for speedtest-go download"
                            )
                            if attempt < max_retries - 1:
                                await asyncio.sleep(retry_delay)
                                continue
                            return False

                    loop = asyncio.get_running_loop()
                    tmp_path = (
                        Path(tempfile.gettempdir())
                        / f"speedtest_go_{info['arch']}.tar.gz"
                    )
                    await loop.run_in_executor(None, tmp_path.write_bytes, data)
                    await loop.run_in_executor(None, self._extract_and_install, tmp_path)
                    _LOGGER.info("Successfully downloaded and installed speedtest-go")
                    return True

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                _LOGGER.warning(
                    "speedtest-go download attempt %d/%d failed: %s",
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    retry_delay = min(retry_delay * 2, 30)
                    continue
                return False
            except (OSError, json.JSONDecodeError, RuntimeError) as e:
                _LOGGER.error("speedtest-go install failed: %s", e)
                return False

        return False

    @staticmethod
    async def _fetch_expected_checksum(
        session: aiohttp.ClientSession, checksums_url: str | None, asset_name: str
    ) -> str | None:
        """Best-effort SHA256 lookup from the release's checksums.txt."""
        if not checksums_url:
            return None
        try:
            async with session.get(checksums_url, allow_redirects=True) as resp:
                if resp.status != HTTP_OK:
                    return None
                for line in (await resp.text()).splitlines():
                    parts = line.split()
                    if len(parts) == 2 and parts[1].lstrip("*") == asset_name:
                        return parts[0].lower()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        return None

    def _extract_and_install(self, tgz_path: Path) -> None:
        """Extract the tarball and install the `speedtest-go` binary (runs in executor)."""
        with tarfile.open(tgz_path, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name == "speedtest-go" or member.name.endswith(
                    "/speedtest-go"
                ):
                    self.cli_path.parent.mkdir(parents=True, exist_ok=True)
                    tar.extract(member, self.cli_path.parent, filter="data")
                    extracted_path = self.cli_path.parent / member.name
                    if extracted_path != self.cli_path:
                        extracted_path.rename(self.cli_path)
                    break
            else:
                raise RuntimeError(
                    "Could not find 'speedtest-go' binary in the downloaded archive"
                )

        self.cli_path.chmod(0o755)
        try:
            tgz_path.unlink(missing_ok=True)
        except OSError:
            pass

    async def ensure_cli_available(self, force_download: bool = False) -> bool:
        """Ensure speedtest-go is available, downloading if necessary."""
        if not force_download and await self.check_cli_exists():
            if self._hass:
                from homeassistant.helpers import issue_registry as ir

                ir.async_delete_issue(self._hass, DOMAIN, "cli_download_failed")
            return True

        _LOGGER.info("speedtest-go not found, attempting to download...")
        success = await self.download_cli()

        if success:
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
        skip_cert_verify: bool = False,  # noqa: ARG002 - speedtest-go has no equivalent flag
        timeout: int = DEFAULT_SPEED_TEST_TIMEOUT,
        source_interface: str | None = None,
        source_ip: str | None = None,
    ) -> dict[str, Any]:
        """Run speed test using speedtest-go and return the unified result dict."""
        if not self.cli_path.exists():
            _LOGGER.error("speedtest-go binary not found at %s", self.cli_path)
            raise CLINotFoundError(
                translation_domain=DOMAIN, translation_key="cli_not_available"
            )

        cmd = [str(self.cli_path), "--json"]

        if custom_server:
            if not self._validate_url(custom_server):
                raise PaceError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_configuration",
                )
            cmd.extend(["--custom-url", custom_server])
        elif server_id is not None:
            if (
                not isinstance(server_id, int)
                or server_id < MIN_SERVER_ID
                or server_id > MAX_SERVER_ID
            ):
                raise PaceError(
                    translation_domain=DOMAIN,
                    translation_key="invalid_configuration",
                )
            cmd.extend(["--server", str(server_id)])

        # speedtest-go has a single --source flag that accepts either an
        # interface name or an IP address.
        if source_interface:
            cmd.extend(["--source", source_interface])
        elif source_ip:
            cmd.extend(["--source", source_ip])

        _LOGGER.info("Running speedtest-go with command: %s", " ".join(cmd))

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
                        "speedtest-go failed with code %d: %s",
                        proc.returncode,
                        error_msg,
                    )
                    raise CLIExecutionError(
                        translation_domain=DOMAIN,
                        translation_key="speed_test_failed",
                        translation_placeholders={"error": error_msg},
                    )

                results = json.loads(stdout.decode())
                # Real `--json` output is an object: {"servers": [...], ...},
                # not a bare array (confirmed against an actual run). Accept
                # a bare list too for resilience against older/newer formats.
                servers = (
                    results.get("servers") or []
                    if isinstance(results, dict)
                    else results
                )
                if not servers:
                    raise CLIOutputError(
                        translation_domain=DOMAIN,
                        translation_key="speed_test_failed",
                        translation_placeholders={"error": "No results from speedtest-go"},
                    )
                return self._parse_raw_result(servers[0], server_id)

        except asyncio.TimeoutError as e:
            _LOGGER.error("speedtest-go test timed out")
            raise SpeedTestTimeoutError(
                translation_domain=DOMAIN,
                translation_key="timeout_error",
                translation_placeholders={"timeout": str(timeout)},
            ) from e
        except json.JSONDecodeError as e:
            _LOGGER.error("Failed to parse speedtest-go output: %s", e)
            raise CLIOutputError(
                translation_domain=DOMAIN,
                translation_key="speed_test_failed",
                translation_placeholders={"error": str(e)},
            ) from e
        except CLIError:
            raise
        except OSError as e:
            _LOGGER.error("speedtest-go process error: %s", e)
            raise CLIExecutionError(
                translation_domain=DOMAIN,
                translation_key="speed_test_failed",
                translation_placeholders={"error": str(e)},
            ) from e

    @staticmethod
    def _validate_url(url: str) -> bool:
        """Validate a custom server URL (same rules as the LibreSpeed backend)."""
        from urllib.parse import urlparse

        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            if not parsed.netloc or len(parsed.netloc) > MAX_HOSTNAME_LENGTH:
                return False
            if any(
                char in url
                for char in ["\n", "\r", "\0", "`", "$", ";", "|", "&", "<", ">"]
            ):
                return False
            return True
        except (ValueError, TypeError, AttributeError):
            return False

    @staticmethod
    def _parse_raw_result(result: dict[str, Any], server_id: int | None) -> dict[str, Any]:
        """Map one entry of speedtest-go's --json output (a Server object) to
        the unified result dict shape.

        Confirmed against a real run: `--json` prints a JSON object shaped
        like `{"servers": [...], "user_info": {...}, ...}`, where each entry
        in `servers` is a `Server` struct with `dl_speed`/`ul_speed` as a
        bytes/sec float (`ByteRate`), and `latency`/`jitter`/`test_duration`
        as Go `time.Duration` values, which marshal to plain integer
        nanoseconds. There is no raw total-bytes-transferred field, so it is
        derived from rate * duration for lifetime data tracking.
        """
        dl_speed_bps = result.get("dl_speed", 0) or 0  # bytes/sec
        ul_speed_bps = result.get("ul_speed", 0) or 0  # bytes/sec
        latency_ns = result.get("latency", 0) or 0
        jitter_ns = result.get("jitter", 0) or 0

        test_duration = result.get("test_duration") or {}
        download_ns = test_duration.get("download", 0) or 0
        upload_ns = test_duration.get("upload", 0) or 0

        return {
            "download": round(dl_speed_bps * 8 / 1_000_000, 2),
            "upload": round(ul_speed_bps * 8 / 1_000_000, 2),
            "ping": round(latency_ns / 1_000_000, 2),
            "jitter": round(jitter_ns / 1_000_000, 2),
            "server": {
                "id": server_id or result.get("id"),
                "name": result.get("name", "Unknown"),
                "location": result.get("country", "Unknown"),
                "sponsor": result.get("sponsor", "speedtest-go"),
            },
            "timestamp": datetime.now(timezone.utc),
            "bytes_sent": round(ul_speed_bps * (upload_ns / 1_000_000_000)),
            "bytes_received": round(dl_speed_bps * (download_ns / 1_000_000_000)),
        }
