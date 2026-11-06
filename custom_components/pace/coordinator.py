"""Data update coordinator for the Pace integration."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any, Final

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .backends.base import SpeedTestBackend

from .const import (
    ATTR_DOWNLOAD_COMPLIANCE,
    ATTR_LIFETIME_DOWNLOAD,
    ATTR_LIFETIME_UPLOAD,
    ATTR_UPLOAD_COMPLIANCE,
    BACKENDS,
    CIRCUIT_BREAKER_OPEN_THRESHOLD,
    CIRCUIT_BREAKER_WARNING_THRESHOLD,
    CONNECTIVITY_CHECK_TIMEOUT,
    CONNECTIVITY_CHECK_URL,
    CONNECTIVITY_HISTORY_SIZE,
    CUSTOM_SERVER_ERROR_COOLDOWN,
    DEFAULT_BACKEND_TYPE,
    DEFAULT_CONNECTIVITY_CHECK_INTERVAL,
    DEFAULT_TEST_TIMEOUT,
    DOMAIN,
    GLOBAL_TEST_LOCK_TIMEOUT,
    HTTP_OK,
    LOGGER_NAME,
    MAX_LIFETIME_GB,
    MAX_RETRIES,
    RETRY_DELAY_BASE,
)
from .exceptions import CLIError, NetworkError, SpeedTestError

_LOGGER: Final = logging.getLogger(LOGGER_NAME)


class PaceDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Class to manage fetching speed test data.

    This coordinator handles speed test execution with proper locking,
    retry logic, and error handling. It's backend-agnostic: `client` can be
    any of the LibreSpeed/Ookla/speedtest-go CLI backends, since they all
    implement the same SpeedTestBackend interface (see backends/base.py).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SpeedTestBackend,
        server_id: int | None,
        custom_server: str | None,
        scan_interval: int,
        auto_update: bool,
        skip_cert_verify: bool = False,
        backend_type: str = DEFAULT_BACKEND_TYPE,
        config_entry: ConfigEntry | None = None,
        test_timeout: int = DEFAULT_TEST_TIMEOUT,
        isp_download_speed: float = 0.0,
        isp_upload_speed: float = 0.0,
        source_interface: str | None = None,
        source_ip: str | None = None,
        start_time: str | None = None,
        fallback_to_closest: bool = False,
        connectivity_check_interval: int = DEFAULT_CONNECTIVITY_CHECK_INTERVAL,
    ) -> None:
        """Initialize the coordinator.

        Args:
            hass: Home Assistant instance.
            client: CLI backend instance (librespeed/ookla/speedtest_go).
            server_id: Optional server ID for testing.
            custom_server: Optional custom server URL.
            scan_interval: Interval between automatic tests in minutes.
            auto_update: Whether to run automatic tests.
            skip_cert_verify: Whether to skip SSL certificate verification.
            backend_type: Which CLI backend this entry uses (see const.BACKENDS).
            config_entry: Config entry for this integration instance.
            test_timeout: Maximum time allowed for a speed test in seconds.
            isp_download_speed: ISP rated download speed in Mbit/s, used to
                calculate plan compliance (0 disables the compliance sensor).
            isp_upload_speed: ISP rated upload speed in Mbit/s, used to
                calculate plan compliance (0 disables the compliance sensor).
            source_interface: Optional network interface name to bind the
                speed test to on the machine running Home Assistant (e.g.
                "eth0"). Passed through to the backend CLI.
            source_ip: Optional source IP address to bind the speed test to
                on the machine running Home Assistant. Passed through to the
                backend CLI.
            start_time: Optional "HH:MM" or "HH:MM:SS" wall-clock time used to
                align the automatic test schedule (e.g. always run on the
                hour). When set, scan_interval still controls the repeat
                interval, but runs are clock-aligned instead of drifting from
                whenever the integration was last reloaded.
            fallback_to_closest: If True, a failed test against a specific
                configured server_id/custom_server is retried once more
                automatically against the closest/automatic server before
                giving up.
            connectivity_check_interval: Seconds between the lightweight
                internet-connectivity/public-IP checks (independent of the
                speed test cycle).
        """
        self.client: SpeedTestBackend = client
        self.server_id: int | None = server_id
        self.custom_server: str | None = custom_server
        self.auto_update: bool = auto_update
        self.skip_cert_verify: bool = skip_cert_verify
        self.backend_type: str = backend_type
        self.entry_title: str = config_entry.title if config_entry else "Pace"
        self.test_timeout: int = test_timeout
        self.isp_download_speed: float = isp_download_speed
        self.isp_upload_speed: float = isp_upload_speed
        self.source_interface: str | None = (source_interface or "").strip() or None
        self.source_ip: str | None = (source_ip or "").strip() or None
        self.start_time: str | None = (start_time or "").strip() or None
        self.scan_interval: int = scan_interval
        self.fallback_to_closest: bool = fallback_to_closest
        self.connectivity_check_interval: int = connectivity_check_interval
        self.is_running: bool = False
        self.is_waiting: bool = False  # Track if waiting for global lock
        self.lifetime_download: float = 0.0  # GB - will be loaded from storage
        self.lifetime_upload: float = 0.0  # GB - will be loaded from storage
        # Updated independently by a lightweight periodic check, not by the
        # speed test cycle - None until the first check has run.
        self.internet_connected: bool | None = None
        self.public_ip: str | None = None
        # Rolling pass/fail history of that same check, oldest first, newest
        # last - feeds the cards' heartbeat-strip trend display.
        self.connectivity_history: deque[bool] = deque(maxlen=CONNECTIVITY_HISTORY_SIZE)
        self._unsub_connectivity_check: Any = None
        self._first_refresh_done: bool = False
        self._test_lock: asyncio.Lock = (
            asyncio.Lock()
        )  # Local lock (kept for compatibility)
        self._global_lock: asyncio.Lock = hass.data[DOMAIN]["test_lock"]  # Global lock
        self._unsub_schedule: Any = None
        # Use entry_id for unique storage key per instance
        entry_id = config_entry.entry_id if config_entry else None
        storage_key = (
            f"{DOMAIN}_lifetime_data_{entry_id}"
            if entry_id
            else f"{DOMAIN}_lifetime_data"
        )
        self._store: Store = Store(hass, 1, storage_key)

        # Failure tracking for repair flows
        self._consecutive_failures: int = 0
        self._last_custom_server_error: float = 0.0

        # If start_time is set, scheduling is handled manually via
        # _schedule_next() so runs stay aligned to the wall-clock instead of
        # drifting based on whenever the integration was last (re)loaded.
        update_interval: timedelta | None = (
            timedelta(minutes=scan_interval)
            if auto_update and not self.start_time
            else None
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=update_interval,
            config_entry=config_entry,
        )

        if config_entry is not None:
            config_entry.async_on_unload(self._cancel_schedule)

    def start_connectivity_check(self) -> None:
        """Arm the periodic connectivity/public-IP check.

        Called explicitly from async_setup_entry() rather than from
        __init__() so constructing a coordinator never has the side effect
        of registering a real HA timer (keeps bare/mocked-config-entry unit
        tests free of lingering timers).
        """
        if self.config_entry is None or self._unsub_connectivity_check is not None:
            return
        self._unsub_connectivity_check = async_track_time_interval(
            self.hass,
            self._async_check_connectivity,
            timedelta(seconds=self.connectivity_check_interval),
        )
        self.config_entry.async_on_unload(self._cancel_connectivity_check)

    async def _async_check_connectivity(self, _now: datetime | None = None) -> None:
        """Check internet reachability and public IP, independent of the speed test cycle.

        Deliberately does not reuse any CLI backend's own client-IP
        reporting - see CONNECTIVITY_CHECK_URL's comment in const.py for why.
        Any failure (offline, DNS down, blocked, timeout, ...) just means
        "not connected right now", not an integration error, so exceptions
        are caught broadly and logged quietly rather than raised.
        """
        session = async_get_clientsession(self.hass)
        connected = False
        try:
            async with asyncio.timeout(CONNECTIVITY_CHECK_TIMEOUT):
                async with session.get(CONNECTIVITY_CHECK_URL) as resp:
                    if resp.status == HTTP_OK:
                        data = await resp.json(content_type=None)
                        self.public_ip = data.get("ip")
                        connected = True
        except Exception as e:  # noqa: BLE001 - any failure just means "offline"
            _LOGGER.debug("Connectivity check failed: %s", e)

        self.internet_connected = connected
        self.connectivity_history.append(connected)
        self.async_update_listeners()

    @callback
    def _cancel_connectivity_check(self) -> None:
        """Cancel the periodic connectivity check (called on entry unload)."""
        if self._unsub_connectivity_check:
            self._unsub_connectivity_check()
            self._unsub_connectivity_check = None

    def _schedule_next(self) -> None:
        """Schedule the next clock-aligned update based on start_time."""
        if not self.start_time:
            return

        try:
            parts = [int(part) for part in self.start_time.split(":")]
            if len(parts) == 2:
                hour, minute = parts
                second = 0
            elif len(parts) == 3:
                hour, minute, second = parts
            else:
                raise ValueError
        except ValueError:
            _LOGGER.error("Invalid start_time format: %s", self.start_time)
            return

        local_now = dt_util.now(time_zone=dt_util.DEFAULT_TIME_ZONE)
        next_run = local_now.replace(
            hour=hour, minute=minute, second=second, microsecond=0
        )

        if next_run <= local_now:
            diff_minutes = (local_now - next_run).total_seconds() / 60
            intervals = int(diff_minutes // self.scan_interval) + 1
            next_run += timedelta(minutes=intervals * self.scan_interval)

        _LOGGER.debug(
            "%s: Scheduling next speed test for %s", self.entry_title, next_run
        )

        if self._unsub_schedule:
            self._unsub_schedule()

        self._unsub_schedule = async_track_point_in_time(
            self.hass, self._async_scheduled_refresh, next_run
        )

    async def _async_scheduled_refresh(self, _now: datetime) -> None:
        """Trigger a refresh from the clock-aligned schedule."""
        await self.async_request_refresh()

    @callback
    def _cancel_schedule(self) -> None:
        """Cancel any pending scheduled refresh (called on entry unload)."""
        if self._unsub_schedule:
            self._unsub_schedule()
            self._unsub_schedule = None

    @property
    def global_lock(self) -> asyncio.Lock:
        """Return the global test lock."""
        return self._global_lock


    @property
    def consecutive_failures(self) -> int:
        """Return the consecutive failure count."""
        return self._consecutive_failures

    @consecutive_failures.setter
    def consecutive_failures(self, value: int) -> None:
        """Set the consecutive failure count."""
        self._consecutive_failures = value

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the configured CLI backend with retry logic and circuit breaker.

        This is the main data update method called by Home Assistant.
        It implements:
        - Circuit breaker pattern (stops after 10 consecutive failures)
        - Concurrency prevention (only one test at a time)
        - Retry logic with exponential backoff
        - Error handling and logging
        - State management (is_running flag)

        Returns:
            Dictionary containing speed test results.

        Raises:
            UpdateFailed: If all retry attempts fail or circuit is open.
        """
        # If a wall-clock schedule is configured, re-arm the next clock
        # aligned run every time an update happens (manual or scheduled).
        if self.start_time and self.auto_update:
            self._schedule_next()

        # Circuit breaker: stop attempting after 10 consecutive failures
        if self._consecutive_failures >= CIRCUIT_BREAKER_OPEN_THRESHOLD:
            _LOGGER.warning(
                "Circuit breaker open - too many consecutive failures (%d). Skipping test.",
                self._consecutive_failures,
            )
            if self.data:
                # Return last known good data
                return self.data
            raise UpdateFailed(
                "Circuit breaker open - service unavailable after 10 consecutive failures"
            )

        # Check if another instance is already testing
        if self._global_lock.locked():
            _LOGGER.info(
                "%s: Another Pace instance is running, waiting...",
                self.entry_title,
            )
            self.is_waiting = True
            self.async_update_listeners()  # Update UI to show waiting status

            try:
                # Wait up to 5 minutes for our turn
                async with asyncio.timeout(GLOBAL_TEST_LOCK_TIMEOUT):
                    async with self._global_lock:
                        self.is_waiting = False
                        return await self._run_speed_test()
            except asyncio.TimeoutError:
                self.is_waiting = False
                _LOGGER.warning(
                    "%s: Timed out waiting for other speed test", self.entry_title
                )
                if self.data:
                    return self.data
                raise UpdateFailed("Timed out waiting for other speed test") from None
        else:
            # No other test running, proceed immediately
            async with self._global_lock:
                return await self._run_speed_test()

    async def _run_speed_test(self) -> dict[str, Any]:
        """Run the actual speed test (called with global lock held)."""
        async with self._test_lock:
            _LOGGER.info("%s: Starting speed test...", self.entry_title)
            try:
                self.is_running = True
                # Notify listeners that test is starting
                self.async_update_listeners()

                try:
                    return await self._attempt_test(self.server_id, self.custom_server)
                except UpdateFailed:
                    # Only fall back once, and only if a specific server was
                    # actually configured (nothing to fall back to otherwise).
                    if self.fallback_to_closest and (
                        self.server_id is not None or self.custom_server
                    ):
                        _LOGGER.warning(
                            "%s: Configured server failed after %d attempts, "
                            "falling back to automatic server selection",
                            self.entry_title,
                            MAX_RETRIES,
                        )
                        return await self._attempt_test(None, None)
                    raise
            finally:
                self.is_running = False
                # Update listeners again to notify binary sensor test is done
                self.async_update_listeners()
                _LOGGER.debug("Speed test finished, is_running set to False")

    async def _attempt_test(
        self, server_id: int | None, custom_server: str | None
    ) -> dict[str, Any]:
        """Run the retry-loop speed test attempt against one server target.

        Raises UpdateFailed if all MAX_RETRIES attempts fail.
        """
        last_error: Exception | None = None

        for attempt in range(MAX_RETRIES):
            try:
                _LOGGER.info(
                    "%s: Starting test (attempt %d/%d) - Server: %s",
                    self.entry_title,
                    attempt + 1,
                    MAX_RETRIES,
                    custom_server or (f"ID {server_id}" if server_id else "Automatic"),
                )

                # Every backend (LibreSpeed/Ookla/speedtest-go)
                # implements the same run_speed_test() signature.
                result = await self.client.run_speed_test(
                    server_id=server_id,
                    custom_server=custom_server,
                    skip_cert_verify=self.skip_cert_verify,
                    timeout=self.test_timeout,
                    source_interface=self.source_interface,
                    source_ip=self.source_ip,
                )

                _LOGGER.debug("Raw speed test result: %s", result)

                # Parse and validate result
                parsed_result: dict[str, Any] = self._parse_result(result)

                # Update lifetime statistics (convert bytes to GB using decimal units)
                # Cap at 1 Petabyte (1,000,000 GB) to prevent overflow
                # MAX_LIFETIME_GB is now in const.py

                if "bytes_received" in parsed_result:
                    new_download = self.lifetime_download + (
                        parsed_result["bytes_received"] / 1_000_000_000
                    )
                    self.lifetime_download = min(new_download, MAX_LIFETIME_GB)
                if "bytes_sent" in parsed_result:
                    new_upload = self.lifetime_upload + (
                        parsed_result["bytes_sent"] / 1_000_000_000
                    )
                    self.lifetime_upload = min(new_upload, MAX_LIFETIME_GB)

                # Save lifetime data to storage
                await self.async_save_lifetime_data()

                # Add lifetime data to result
                parsed_result[ATTR_LIFETIME_DOWNLOAD] = self.lifetime_download
                parsed_result[ATTR_LIFETIME_UPLOAD] = self.lifetime_upload

                # Reset failure counter on success and clear any repair issues
                self._consecutive_failures = 0
                from homeassistant.helpers import issue_registry as ir

                ir.async_delete_issue(
                    self.hass, DOMAIN, "custom_server_unreachable"
                )
                ir.async_delete_issue(
                    self.hass, DOMAIN, "repeated_test_failures"
                )

                # Log success
                _LOGGER.info(
                    "Speed test completed: ↓ %.1f Mbps | ↑ %.1f Mbps | Ping: %.1f ms",
                    parsed_result.get("download", 0),
                    parsed_result.get("upload", 0),
                    parsed_result.get("ping", 0),
                )
                return parsed_result

            except asyncio.TimeoutError as err:
                last_error = err
                _LOGGER.warning(
                    "Speed test timeout (attempt %d/%d)",
                    attempt + 1,
                    MAX_RETRIES,
                )
                if attempt < MAX_RETRIES - 1:
                    # Exponential backoff with jitter
                    delay: float = RETRY_DELAY_BASE * (2**attempt)
                    await asyncio.sleep(delay)
                    continue

            except aiohttp.ClientError as err:
                last_error = err
                _LOGGER.warning(
                    "Network error (attempt %d/%d): %s",
                    attempt + 1,
                    MAX_RETRIES,
                    err.__class__.__name__,
                )
                if attempt < MAX_RETRIES - 1:
                    # Exponential backoff with jitter
                    delay: float = RETRY_DELAY_BASE * (2**attempt)
                    await asyncio.sleep(delay)
                    continue

            except (SpeedTestError, NetworkError, CLIError) as err:
                # Don't retry on known errors
                _LOGGER.error("Speed test error: %s", err)
                raise UpdateFailed(f"Speed test error: {err}") from err
            except (ValueError, TypeError, KeyError, AttributeError) as err:
                # Don't retry on data/parsing errors
                _LOGGER.exception("Data processing error during speed test")
                raise UpdateFailed(f"Data processing error: {err}") from err

        # If we get here, all retries failed - track failures for repair issues
        self._consecutive_failures += 1

        # Check for custom server issues (only if using custom server)
        if custom_server and isinstance(
            last_error, (aiohttp.ClientError, NetworkError)
        ):
            current_time = time.time()
            # Create repair issue if we haven't created one recently (last 6 hours)
            if (
                current_time - self._last_custom_server_error
                > CUSTOM_SERVER_ERROR_COOLDOWN
            ):
                self._last_custom_server_error = current_time
                from homeassistant.helpers import issue_registry as ir

                ir.async_create_issue(
                    self.hass,
                    DOMAIN,
                    "custom_server_unreachable",
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="custom_server_unreachable",
                    translation_placeholders={
                        "options_path": "Settings → Devices & Services → Pace → Configure"
                    },
                )

        # Check for repeated failures and create repair issues
        from homeassistant.helpers import issue_registry as ir

        if self._consecutive_failures == CIRCUIT_BREAKER_WARNING_THRESHOLD:
            # First warning at 5 failures
            other_backends = [
                b for b in BACKENDS if b != self.backend_type
            ]
            backend_switch = (
                f"Try switching to a different backend ({', '.join(other_backends)})"
            )
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "repeated_test_failures",
                is_fixable=True,  # Make it fixable since we have a repair flow
                severity=ir.IssueSeverity.WARNING,
                translation_key="repeated_test_failures",
                translation_placeholders={
                    "backend_switch": backend_switch,
                    "options_path": "Settings → Devices & Services → Pace → Configure",
                },
            )
        elif self._consecutive_failures == CIRCUIT_BREAKER_OPEN_THRESHOLD:
            # Circuit breaker opened at 10 failures
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                "circuit_breaker_open",
                is_fixable=True,
                severity=ir.IssueSeverity.ERROR,
                translation_key="circuit_breaker_open",
                translation_placeholders={
                    "failure_count": str(self._consecutive_failures),
                    "manual_test": "You can try a manual test to reset the circuit breaker",
                },
            )

        if isinstance(last_error, asyncio.TimeoutError):
            raise UpdateFailed(
                "Speed test timed out after multiple attempts"
            ) from last_error
        if isinstance(last_error, aiohttp.ClientError):
            raise UpdateFailed(
                f"Network error after multiple attempts: {last_error}"
            ) from last_error
        raise UpdateFailed("Speed test failed after multiple attempts")

    def _parse_result(self, result: dict) -> dict[str, Any]:
        """Parse the speedtest result into a standardized format."""
        download = result.get("download", 0)
        upload = result.get("upload", 0)
        parsed: dict[str, Any] = {
            "download": download,
            "upload": upload,
            "ping": result.get("ping", 0),
            "jitter": result.get("jitter", 0),
            "server_name": result.get("server", {}).get("name", "Unknown"),
            "server_location": result.get("server", {}).get("location", "Unknown"),
            "server_sponsor": result.get("server", {}).get("sponsor", "Unknown"),
            "timestamp": result.get("timestamp"),  # This is already a datetime object
            "bytes_sent": result.get("bytes_sent", 0),
            "bytes_received": result.get("bytes_received", 0),
        }

        # Plan compliance is only meaningful once the user has configured
        # their ISP's rated speed; otherwise the sensor stays unavailable.
        if self.isp_download_speed > 0:
            parsed[ATTR_DOWNLOAD_COMPLIANCE] = round(
                (download / self.isp_download_speed) * 100, 1
            )
        if self.isp_upload_speed > 0:
            parsed[ATTR_UPLOAD_COMPLIANCE] = round(
                (upload / self.isp_upload_speed) * 100, 1
            )

        return parsed

    async def async_get_server_list(self) -> list[dict[str, Any]]:
        """Get list of available servers."""
        try:
            # CLI backend doesn't support server discovery
            if hasattr(self.client, "get_servers"):
                return await self.client.get_servers()
            _LOGGER.debug("Server list not supported by %s backend", self.backend_type)
            return []
        except (NetworkError, aiohttp.ClientError, asyncio.TimeoutError):
            _LOGGER.debug("Failed to fetch server list")
            return []

    async def async_run_speedtest(self) -> None:
        """Manually trigger a speedtest.

        Manual tests reset the circuit breaker to allow recovery attempts.
        """
        # Reset circuit breaker on manual test - user wants to try again
        if self._consecutive_failures >= CIRCUIT_BREAKER_OPEN_THRESHOLD:
            _LOGGER.info("Resetting circuit breaker for manual test attempt")
            self._consecutive_failures = 0

        await self.async_refresh()

    async def async_load_lifetime_data(self) -> None:
        """Load lifetime data and last test results from storage."""
        try:
            stored_data = await self._store.async_load()
            if stored_data:
                self.lifetime_download = stored_data.get("lifetime_download", 0.0)
                self.lifetime_upload = stored_data.get("lifetime_upload", 0.0)

                # Restore ALL test data to avoid "Unknown" sensors after reload
                if last_test_data := stored_data.get("last_test_data"):
                    # Convert timestamp string back to datetime if present
                    timestamp = last_test_data.get("timestamp")
                    if timestamp and isinstance(timestamp, str):
                        try:
                            timestamp = datetime.fromisoformat(timestamp)
                        except (ValueError, TypeError):
                            timestamp = None

                    # Ensure ALL fields are present with proper types
                    self.data = {
                        "download": last_test_data.get("download", 0),
                        "upload": last_test_data.get("upload", 0),
                        "ping": last_test_data.get("ping", 0),
                        "jitter": last_test_data.get("jitter", 0),
                        "server_name": last_test_data.get("server_name", "Unknown"),
                        "server_location": last_test_data.get(
                            "server_location", "Unknown"
                        ),
                        "server_sponsor": last_test_data.get(
                            "server_sponsor", "Unknown"
                        ),
                        "timestamp": timestamp,
                        "bytes_sent": last_test_data.get("bytes_sent", 0),
                        "bytes_received": last_test_data.get("bytes_received", 0),
                        ATTR_LIFETIME_DOWNLOAD: self.lifetime_download,
                        ATTR_LIFETIME_UPLOAD: self.lifetime_upload,
                        ATTR_DOWNLOAD_COMPLIANCE: last_test_data.get(
                            ATTR_DOWNLOAD_COMPLIANCE
                        ),
                        ATTR_UPLOAD_COMPLIANCE: last_test_data.get(
                            ATTR_UPLOAD_COMPLIANCE
                        ),
                    }
                    _LOGGER.info(
                        "Restored complete test data: ↓ %.1f Mbps | ↑ %.1f Mbps | Ping: %.1f ms | Jitter: %.1f ms | Server: %s",
                        self.data.get("download", 0),
                        self.data.get("upload", 0),
                        self.data.get("ping", 0),
                        self.data.get("jitter", 0),
                        self.data.get("server_name", "Unknown"),
                    )

                _LOGGER.info(
                    "Loaded lifetime data: ↓ %.2f GB | ↑ %.2f GB",
                    self.lifetime_download,
                    self.lifetime_upload,
                )

                # Notify listeners that we have data
                if self.data:
                    self.async_set_updated_data(self.data)
        except Exception as err:  # noqa: BLE001 - broad catch for storage operations
            _LOGGER.warning("Failed to load lifetime data: %s", err)

    async def async_save_lifetime_data(self) -> None:
        """Save lifetime data and last test results to storage."""
        try:
            # Prepare data for JSON serialization
            save_data = {
                "lifetime_download": self.lifetime_download,
                "lifetime_upload": self.lifetime_upload,
            }

            # Convert datetime to string for JSON serialization
            if self.data:
                last_test_data = self.data.copy()
                if "timestamp" in last_test_data and isinstance(
                    last_test_data["timestamp"], datetime
                ):
                    last_test_data["timestamp"] = last_test_data[
                        "timestamp"
                    ].isoformat()
                save_data["last_test_data"] = last_test_data

            await self._store.async_save(save_data)
        except Exception as err:  # noqa: BLE001 - broad catch for storage operations
            _LOGGER.warning("Failed to save lifetime data: %s", err)
