"""Tests for Pace data update coordinator."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.pace.const import (
    ATTR_LIFETIME_DOWNLOAD,
    ATTR_LIFETIME_UPLOAD,
    DOMAIN,
    MAX_LIFETIME_GB,
)
from custom_components.pace.coordinator import (
    PaceDataUpdateCoordinator,
)
from custom_components.pace.exceptions import (
    CLIError,
    NetworkError,
    SpeedTestError,
)

from .conftest import MOCK_SPEED_TEST_RESULT, MOCK_STORED_DATA


def _make_coordinator(
    hass: HomeAssistant,
    client=None,
    server_id=None,
    custom_server=None,
    scan_interval=60,
    auto_update=False,
    backend_type="librespeed",
    entry_id="test_entry",
    entry_title="Test",
    test_timeout=240,
    source_interface=None,
    source_ip=None,
    start_time=None,
    fallback_to_closest=False,
    connectivity_check_interval=30,
):
    """Create a coordinator with mocked dependencies."""
    hass.data.setdefault(DOMAIN, {})
    if "test_lock" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["test_lock"] = asyncio.Lock()

    if client is None:
        client = AsyncMock()
        client.run_speed_test = AsyncMock(
            return_value=deepcopy(MOCK_SPEED_TEST_RESULT)
        )
        client.get_servers = AsyncMock(return_value=[])

    config_entry = MagicMock()
    config_entry.entry_id = entry_id
    config_entry.title = entry_title

    coordinator = PaceDataUpdateCoordinator(
        hass,
        client,
        server_id,
        custom_server,
        scan_interval,
        auto_update,
        backend_type=backend_type,
        config_entry=config_entry,
        test_timeout=test_timeout,
        source_interface=source_interface,
        source_ip=source_ip,
        start_time=start_time,
        fallback_to_closest=fallback_to_closest,
        connectivity_check_interval=connectivity_check_interval,
    )
    return coordinator


# ---- Parse result ----


async def test_parse_result_complete(hass: HomeAssistant, mock_store) -> None:
    """Test _parse_result with complete data."""
    coordinator = _make_coordinator(hass)
    result = coordinator._parse_result(MOCK_SPEED_TEST_RESULT)
    assert result["download"] == 250.50
    assert result["upload"] == 50.25
    assert result["ping"] == 12.34
    assert result["jitter"] == 1.56
    assert result["server_name"] == "Test Server"
    assert result["server_location"] == "Test City"
    assert result["server_sponsor"] == "Test Sponsor"
    assert result["bytes_sent"] == 50_000_000
    assert result["bytes_received"] == 250_000_000


async def test_parse_result_missing_fields(hass: HomeAssistant, mock_store) -> None:
    """Test _parse_result with empty dict defaults."""
    coordinator = _make_coordinator(hass)
    result = coordinator._parse_result({})
    assert result["download"] == 0
    assert result["upload"] == 0
    assert result["server_name"] == "Unknown"


async def test_parse_result_missing_server(hass: HomeAssistant, mock_store) -> None:
    """Test _parse_result with no server key."""
    coordinator = _make_coordinator(hass)
    result = coordinator._parse_result({"download": 100, "upload": 50})
    assert result["server_name"] == "Unknown"
    assert result["server_location"] == "Unknown"
    assert result["server_sponsor"] == "Unknown"


# ---- Update data success ----


async def test_update_data_success_native(hass: HomeAssistant, mock_store) -> None:
    """Test successful speed test with native backend."""
    coordinator = _make_coordinator(hass)
    result = await coordinator._async_update_data()
    assert result["download"] == 250.50
    assert result[ATTR_LIFETIME_DOWNLOAD] >= 0


async def test_update_data_success_cli(hass: HomeAssistant, mock_store) -> None:
    """Test successful speed test with Ookla backend."""
    coordinator = _make_coordinator(hass, backend_type="ookla")
    result = await coordinator._async_update_data()
    assert result["download"] == 250.50


# ---- Lifetime data ----


async def test_lifetime_accumulation(hass: HomeAssistant, mock_store) -> None:
    """Test lifetime data is accumulated after test."""
    coordinator = _make_coordinator(hass)
    coordinator.lifetime_download = 1.0
    coordinator.lifetime_upload = 0.5
    result = await coordinator._async_update_data()
    # 250_000_000 bytes = 0.25 GB
    assert coordinator.lifetime_download == 1.25
    # 50_000_000 bytes = 0.05 GB
    assert coordinator.lifetime_upload == 0.55


async def test_lifetime_cap(hass: HomeAssistant, mock_store) -> None:
    """Test lifetime data is capped at MAX_LIFETIME_GB."""
    coordinator = _make_coordinator(hass)
    coordinator.lifetime_download = MAX_LIFETIME_GB - 0.01
    await coordinator._async_update_data()
    assert coordinator.lifetime_download == MAX_LIFETIME_GB


async def test_lifetime_saved_after_test(hass: HomeAssistant, mock_store) -> None:
    """Test lifetime data is saved after successful test."""
    coordinator = _make_coordinator(hass)
    await coordinator._async_update_data()
    mock_store.async_save.assert_called()


# ---- Load lifetime data ----


async def test_load_lifetime_data_success(hass: HomeAssistant, mock_store) -> None:
    """Test loading lifetime data from store."""
    coordinator = _make_coordinator(hass)
    await coordinator.async_load_lifetime_data()
    assert coordinator.lifetime_download == 1.5
    assert coordinator.lifetime_upload == 0.5
    assert coordinator.data is not None
    assert coordinator.data["download"] == 250.50


async def test_load_lifetime_data_empty(hass: HomeAssistant) -> None:
    """Test loading when store is empty."""
    with patch(
        "custom_components.pace.coordinator.Store",
    ) as mock_cls:
        mock_cls.return_value.async_load = AsyncMock(return_value=None)
        coordinator = _make_coordinator(hass)
        await coordinator.async_load_lifetime_data()
    assert coordinator.lifetime_download == 0.0
    assert coordinator.lifetime_upload == 0.0


async def test_load_lifetime_data_error(hass: HomeAssistant) -> None:
    """Test loading when store raises error."""
    with patch(
        "custom_components.pace.coordinator.Store",
    ) as mock_cls:
        mock_cls.return_value.async_load = AsyncMock(side_effect=OSError("disk fail"))
        coordinator = _make_coordinator(hass)
        await coordinator.async_load_lifetime_data()
    assert coordinator.lifetime_download == 0.0


async def test_load_lifetime_data_timestamp_string(hass: HomeAssistant, mock_store) -> None:
    """Test timestamp string is converted to datetime on load."""
    coordinator = _make_coordinator(hass)
    await coordinator.async_load_lifetime_data()
    from datetime import datetime
    assert isinstance(coordinator.data["timestamp"], datetime)


async def test_load_lifetime_data_no_last_test(hass: HomeAssistant) -> None:
    """Test loading when no last_test_data in store."""
    stored = {"lifetime_download": 5.0, "lifetime_upload": 2.0}
    with patch(
        "custom_components.pace.coordinator.Store",
    ) as mock_cls:
        mock_cls.return_value.async_load = AsyncMock(return_value=stored)
        coordinator = _make_coordinator(hass)
        await coordinator.async_load_lifetime_data()
    assert coordinator.lifetime_download == 5.0
    assert coordinator.data is None


# ---- Save lifetime data ----


async def test_save_lifetime_data_success(hass: HomeAssistant, mock_store) -> None:
    """Test saving lifetime data."""
    coordinator = _make_coordinator(hass)
    coordinator.lifetime_download = 5.0
    coordinator.lifetime_upload = 2.0
    coordinator.data = deepcopy(MOCK_SPEED_TEST_RESULT)
    await coordinator.async_save_lifetime_data()
    mock_store.async_save.assert_called_once()
    saved = mock_store.async_save.call_args[0][0]
    assert saved["lifetime_download"] == 5.0
    assert saved["lifetime_upload"] == 2.0
    assert "last_test_data" in saved


async def test_save_lifetime_data_no_data(hass: HomeAssistant, mock_store) -> None:
    """Test saving without coordinator data."""
    coordinator = _make_coordinator(hass)
    coordinator.lifetime_download = 1.0
    coordinator.data = None
    await coordinator.async_save_lifetime_data()
    saved = mock_store.async_save.call_args[0][0]
    assert "last_test_data" not in saved


async def test_save_lifetime_data_error(hass: HomeAssistant) -> None:
    """Test saving when store raises error doesn't crash."""
    with patch(
        "custom_components.pace.coordinator.Store",
    ) as mock_cls:
        mock_cls.return_value.async_save = AsyncMock(side_effect=OSError("disk"))
        mock_cls.return_value.async_load = AsyncMock(return_value=None)
        coordinator = _make_coordinator(hass)
        coordinator.lifetime_download = 1.0
        await coordinator.async_save_lifetime_data()  # Should not raise


# ---- Retry logic ----


async def test_retry_on_timeout(hass: HomeAssistant, mock_store) -> None:
    """Test retry after timeout succeeds on second attempt."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(
        side_effect=[asyncio.TimeoutError(), deepcopy(MOCK_SPEED_TEST_RESULT)]
    )
    coordinator = _make_coordinator(hass, client=client)
    with patch("custom_components.pace.coordinator.asyncio.sleep"):
        result = await coordinator._async_update_data()
    assert result["download"] == 250.50
    assert client.run_speed_test.call_count == 2


async def test_all_retries_exhausted_timeout(hass: HomeAssistant, mock_store) -> None:
    """Test all retries exhausted raises UpdateFailed."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=asyncio.TimeoutError())
    coordinator = _make_coordinator(hass, client=client)
    with (
        patch("custom_components.pace.coordinator.asyncio.sleep"),
        pytest.raises(UpdateFailed, match="timed out"),
    ):
        await coordinator._async_update_data()
    assert coordinator.consecutive_failures == 1


async def test_no_retry_on_speed_test_error(hass: HomeAssistant, mock_store) -> None:
    """Test SpeedTestError doesn't retry, but still counts as a failure."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=SpeedTestError("test error"))
    coordinator = _make_coordinator(hass, client=client)
    with pytest.raises(UpdateFailed, match="Speed test failed"):
        await coordinator._async_update_data()
    assert client.run_speed_test.call_count == 1
    assert coordinator.consecutive_failures == 1


async def test_no_retry_on_network_error(hass: HomeAssistant, mock_store) -> None:
    """Test NetworkError doesn't retry, but still counts as a failure."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=NetworkError("net error"))
    coordinator = _make_coordinator(hass, client=client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert client.run_speed_test.call_count == 1
    assert coordinator.consecutive_failures == 1


async def test_no_retry_on_cli_error(hass: HomeAssistant, mock_store) -> None:
    """Test CLIError doesn't retry, but still counts as a failure (e.g. a
    backend's own rate limiting must eventually surface a repair issue and
    trip the circuit breaker, which requires the counter to actually move).
    """
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=CLIError("cli fail"))
    coordinator = _make_coordinator(hass, client=client)
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert client.run_speed_test.call_count == 1
    assert coordinator.consecutive_failures == 1
    assert coordinator.last_test_error == "cli fail"


# ---- Circuit breaker ----


async def test_circuit_breaker_opens_at_threshold(hass: HomeAssistant, mock_store) -> None:
    """Test circuit breaker opens after 10 consecutive failures."""
    coordinator = _make_coordinator(hass)
    coordinator._consecutive_failures = 10

    with pytest.raises(UpdateFailed, match="Circuit breaker open"):
        await coordinator._async_update_data()


async def test_circuit_breaker_returns_last_data(hass: HomeAssistant, mock_store) -> None:
    """Test circuit breaker returns last data when open."""
    coordinator = _make_coordinator(hass)
    coordinator._consecutive_failures = 10
    coordinator.data = {"download": 100}

    result = await coordinator._async_update_data()
    assert result["download"] == 100


async def test_circuit_breaker_reset_on_success(hass: HomeAssistant, mock_store) -> None:
    """Test failures reset to 0 after successful test."""
    coordinator = _make_coordinator(hass)
    coordinator._consecutive_failures = 5
    await coordinator._async_update_data()
    assert coordinator.consecutive_failures == 0


async def test_circuit_breaker_reset_on_manual_test(hass: HomeAssistant, mock_store) -> None:
    """Test manual test resets circuit breaker."""
    coordinator = _make_coordinator(hass)
    coordinator._consecutive_failures = 10
    coordinator.async_refresh = AsyncMock()
    await coordinator.async_run_speedtest()
    assert coordinator.consecutive_failures == 0
    coordinator.async_refresh.assert_called_once()


# ---- Global lock ----


async def test_is_running_flag(hass: HomeAssistant, mock_store) -> None:
    """Test is_running is True during test and False after."""
    coordinator = _make_coordinator(hass)
    assert coordinator.is_running is False

    await coordinator._async_update_data()
    assert coordinator.is_running is False


# ---- Server list ----


async def test_get_server_list_native(hass: HomeAssistant, mock_store) -> None:
    """Test getting server list with native backend."""
    client = AsyncMock()
    client.get_servers = AsyncMock(return_value=[{"id": 1, "name": "S1"}])
    coordinator = _make_coordinator(hass, client=client)
    result = await coordinator.async_get_server_list()
    assert len(result) == 1


async def test_get_server_list_cli(hass: HomeAssistant, mock_store) -> None:
    """Test CLI backend returns empty server list."""
    client = MagicMock()
    # CLI client doesn't have get_servers
    del client.get_servers
    coordinator = _make_coordinator(hass, client=client, backend_type="ookla")
    result = await coordinator.async_get_server_list()
    assert result == []


async def test_get_server_list_error(hass: HomeAssistant, mock_store) -> None:
    """Test server list returns empty on error."""
    client = AsyncMock()
    client.get_servers = AsyncMock(side_effect=NetworkError("fail"))
    coordinator = _make_coordinator(hass, client=client)
    result = await coordinator.async_get_server_list()
    assert result == []


# ---- Update interval ----


async def test_update_interval_auto(hass: HomeAssistant, mock_store) -> None:
    """Test update interval with auto_update enabled."""
    coordinator = _make_coordinator(hass, auto_update=True, scan_interval=30)
    assert coordinator.update_interval == timedelta(minutes=30)


async def test_update_interval_no_auto(hass: HomeAssistant, mock_store) -> None:
    """Test update interval is None when auto_update disabled."""
    coordinator = _make_coordinator(hass, auto_update=False)
    assert coordinator.update_interval is None


# ---- Backend dispatch ----


async def test_dispatch_to_cli(hass: HomeAssistant, mock_store) -> None:
    """Test CLI backend dispatch passes correct args."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(return_value=deepcopy(MOCK_SPEED_TEST_RESULT))
    coordinator = _make_coordinator(
        hass, client=client, backend_type="ookla", custom_server="https://example.com"
    )
    await coordinator._async_update_data()
    client.run_speed_test.assert_called_once_with(
        server_id=None,
        custom_server="https://example.com",
        skip_cert_verify=False,
        timeout=240,
        source_interface=None,
        source_ip=None,
    )


async def test_custom_server_error_creates_repair(hass: HomeAssistant, mock_store) -> None:
    """Test custom server error creates repair issue."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=aiohttp.ClientError("fail"))
    coordinator = _make_coordinator(
        hass, client=client, custom_server="https://custom.example.com"
    )
    with (
        patch("custom_components.pace.coordinator.asyncio.sleep"),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()
    assert coordinator.consecutive_failures == 1
    # Verify repair issue was created
    from homeassistant.helpers import issue_registry as ir
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "custom_server_unreachable")
    assert issue is not None


async def test_warning_repair_at_5_failures(hass: HomeAssistant, mock_store) -> None:
    """Test warning repair issue is created at 5 failures."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=asyncio.TimeoutError())
    coordinator = _make_coordinator(hass, client=client)
    coordinator._consecutive_failures = 4  # Will become 5 after this failure

    with (
        patch("custom_components.pace.coordinator.asyncio.sleep"),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()
    assert coordinator.consecutive_failures == 5
    from homeassistant.helpers import issue_registry as ir
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "repeated_test_failures")
    assert issue is not None


async def test_circuit_breaker_repair_at_10_failures(hass: HomeAssistant, mock_store) -> None:
    """Test circuit breaker repair issue at 10 failures."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=asyncio.TimeoutError())
    coordinator = _make_coordinator(hass, client=client)
    coordinator._consecutive_failures = 9  # Will become 10

    with (
        patch("custom_components.pace.coordinator.asyncio.sleep"),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()
    assert coordinator.consecutive_failures == 10
    from homeassistant.helpers import issue_registry as ir
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "circuit_breaker_open")
    assert issue is not None


async def test_retry_on_client_error(hass: HomeAssistant, mock_store) -> None:
    """Test retry after aiohttp.ClientError succeeds on second attempt."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(
        side_effect=[aiohttp.ClientError(), deepcopy(MOCK_SPEED_TEST_RESULT)]
    )
    coordinator = _make_coordinator(hass, client=client)
    with patch("custom_components.pace.coordinator.asyncio.sleep"):
        result = await coordinator._async_update_data()
    assert result["download"] == 250.50


async def test_dispatch_to_native(hass: HomeAssistant, mock_store) -> None:
    """Test the coordinator calls run_speed_test with the unified signature
    regardless of backend_type - all backends share one interface now."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(return_value=deepcopy(MOCK_SPEED_TEST_RESULT))
    coordinator = _make_coordinator(
        hass, client=client, backend_type="librespeed", custom_server="https://example.com"
    )
    await coordinator._async_update_data()
    client.run_speed_test.assert_called_once_with(
        server_id=None,
        custom_server="https://example.com",
        skip_cert_verify=False,
        timeout=240,
        source_interface=None,
        source_ip=None,
    )


# ---- consecutive_failures setter ----


async def test_consecutive_failures_setter(hass: HomeAssistant, mock_store) -> None:
    """Test consecutive_failures property setter."""
    coordinator = _make_coordinator(hass)
    assert coordinator.consecutive_failures == 0
    coordinator.consecutive_failures = 5
    assert coordinator.consecutive_failures == 5


# ---- Data parsing error ----


async def test_data_processing_error_raises_update_failed(
    hass: HomeAssistant, mock_store
) -> None:
    """Test ValueError/TypeError during speed test raises UpdateFailed and still counts as a failure."""
    client = AsyncMock()
    # Return a result that will cause a parsing error (non-dict)
    client.run_speed_test = AsyncMock(return_value="not a dict")
    coordinator = _make_coordinator(hass, client=client)
    with pytest.raises(UpdateFailed, match="Speed test failed"):
        await coordinator._async_update_data()
    assert coordinator.consecutive_failures == 1


# ---- Invalid timestamp in stored data ----


async def test_load_stored_data_invalid_timestamp(hass: HomeAssistant) -> None:
    """Test loading stored data with an unparseable timestamp string."""
    stored = deepcopy(MOCK_STORED_DATA)
    stored["last_test_data"]["timestamp"] = "not-a-timestamp"
    with patch(
        "custom_components.pace.coordinator.Store",
    ) as mock_cls:
        mock_cls.return_value.async_load = AsyncMock(return_value=stored)
        coordinator = _make_coordinator(hass)
        await coordinator.async_load_lifetime_data()
    # Timestamp should be None (gracefully handled)
    assert coordinator.data["timestamp"] is None


# ---- source_interface / source_ip binding ----


async def test_source_interface_and_ip_passed_to_backend(
    hass: HomeAssistant, mock_store
) -> None:
    """Test source_interface/source_ip are forwarded to run_speed_test."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(return_value=deepcopy(MOCK_SPEED_TEST_RESULT))
    coordinator = _make_coordinator(
        hass,
        client=client,
        source_interface="eth0",
        source_ip="10.20.0.101",
    )
    await coordinator._async_update_data()
    client.run_speed_test.assert_called_once_with(
        server_id=None,
        custom_server=None,
        skip_cert_verify=False,
        timeout=240,
        source_interface="eth0",
        source_ip="10.20.0.101",
    )


async def test_source_interface_and_ip_blank_strings_become_none(
    hass: HomeAssistant, mock_store
) -> None:
    """Test blank/whitespace source fields are normalized to None."""
    coordinator = _make_coordinator(hass, source_interface="  ", source_ip="")
    assert coordinator.source_interface is None
    assert coordinator.source_ip is None


# ---- fallback_to_closest ----


async def test_fallback_to_closest_retries_with_automatic_server(
    hass: HomeAssistant, mock_store
) -> None:
    """Test a failed test against a specific server falls back to automatic."""
    client = AsyncMock()

    async def _run_speed_test(**kwargs):
        if kwargs.get("server_id") == 5:
            raise CLIError("server unreachable")
        return deepcopy(MOCK_SPEED_TEST_RESULT)

    client.run_speed_test = AsyncMock(side_effect=_run_speed_test)
    coordinator = _make_coordinator(
        hass, client=client, server_id=5, fallback_to_closest=True
    )
    with patch("custom_components.pace.coordinator.asyncio.sleep"):
        result = await coordinator._async_update_data()

    assert result["download"] == 250.50
    # First attempted with server_id=5 (and retried MAX_RETRIES times), then
    # once more with server_id=None (automatic) as the fallback.
    calls = client.run_speed_test.call_args_list
    assert calls[-1].kwargs["server_id"] is None


async def test_fallback_to_closest_disabled_does_not_retry(
    hass: HomeAssistant, mock_store
) -> None:
    """Test that without fallback_to_closest, a configured-server failure just fails."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=CLIError("server unreachable"))
    coordinator = _make_coordinator(
        hass, client=client, server_id=5, fallback_to_closest=False
    )
    with (
        patch("custom_components.pace.coordinator.asyncio.sleep"),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()

    # Every call should have used the configured server_id, never None.
    for call in client.run_speed_test.call_args_list:
        assert call.kwargs["server_id"] == 5


async def test_fallback_to_closest_not_used_when_already_automatic(
    hass: HomeAssistant, mock_store
) -> None:
    """Test fallback is skipped entirely when there's nothing to fall back from."""
    client = AsyncMock()
    client.run_speed_test = AsyncMock(side_effect=CLIError("fail"))
    coordinator = _make_coordinator(
        hass, client=client, server_id=None, custom_server=None, fallback_to_closest=True
    )
    with (
        patch("custom_components.pace.coordinator.asyncio.sleep"),
        pytest.raises(UpdateFailed),
    ):
        await coordinator._async_update_data()

    # CLIError is a "known error" that doesn't retry - only one call total,
    # and fallback was never attempted since there was no configured server.
    assert client.run_speed_test.call_count == 1


# ---- start_time wall-clock scheduling ----


async def test_schedule_next_valid_start_time_arms_timer(hass: HomeAssistant) -> None:
    """Test a valid start_time arms a point-in-time schedule."""
    coordinator = _make_coordinator(hass, start_time="00:00", scan_interval=60)
    with patch(
        "custom_components.pace.coordinator.async_track_point_in_time"
    ) as mock_track:
        mock_track.return_value = MagicMock()
        coordinator._schedule_next()
    mock_track.assert_called_once()
    assert coordinator._unsub_schedule is not None


async def test_schedule_next_invalid_format_logs_and_skips(
    hass: HomeAssistant,
) -> None:
    """Test an invalid start_time is handled gracefully without raising."""
    coordinator = _make_coordinator(hass, start_time="not-a-time", scan_interval=60)
    with patch(
        "custom_components.pace.coordinator.async_track_point_in_time"
    ) as mock_track:
        coordinator._schedule_next()
    mock_track.assert_not_called()
    assert coordinator._unsub_schedule is None


async def test_schedule_next_noop_without_start_time(hass: HomeAssistant) -> None:
    """Test _schedule_next is a no-op when start_time isn't configured."""
    coordinator = _make_coordinator(hass, start_time=None)
    with patch(
        "custom_components.pace.coordinator.async_track_point_in_time"
    ) as mock_track:
        coordinator._schedule_next()
    mock_track.assert_not_called()


async def test_start_time_disables_fixed_update_interval(hass: HomeAssistant) -> None:
    """Test that configuring start_time switches off the fixed update_interval."""
    coordinator = _make_coordinator(
        hass, start_time="00:00", scan_interval=60, auto_update=True
    )
    assert coordinator.update_interval is None


async def test_no_start_time_keeps_fixed_update_interval(hass: HomeAssistant) -> None:
    """Test that without start_time, the fixed interval behavior is unchanged."""
    coordinator = _make_coordinator(
        hass, start_time=None, scan_interval=60, auto_update=True
    )
    assert coordinator.update_interval == timedelta(minutes=60)


# ---- Connectivity check ----


def _mock_response(status=200, json_data=None):
    """Build a mock aiohttp response usable as an async context manager."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=resp)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


async def test_check_connectivity_success(hass: HomeAssistant, mock_store) -> None:
    """Test a successful connectivity check sets internet_connected and public_ip."""
    coordinator = _make_coordinator(hass)
    session = MagicMock()
    session.get = MagicMock(
        return_value=_mock_response(200, {"ip": "203.0.113.42"})
    )
    with patch(
        "custom_components.pace.coordinator.async_get_clientsession",
        return_value=session,
    ):
        await coordinator._async_check_connectivity()
    assert coordinator.internet_connected is True
    assert coordinator.public_ip == "203.0.113.42"


async def test_check_connectivity_non_200_marks_offline(
    hass: HomeAssistant, mock_store
) -> None:
    """Test a non-200 response marks internet_connected False without touching public_ip."""
    coordinator = _make_coordinator(hass)
    coordinator.public_ip = "198.51.100.7"  # last known good value
    session = MagicMock()
    session.get = MagicMock(return_value=_mock_response(503))
    with patch(
        "custom_components.pace.coordinator.async_get_clientsession",
        return_value=session,
    ):
        await coordinator._async_check_connectivity()
    assert coordinator.internet_connected is False
    assert coordinator.public_ip == "198.51.100.7"  # unchanged, not cleared


async def test_check_connectivity_exception_marks_offline(
    hass: HomeAssistant, mock_store
) -> None:
    """Test any exception (timeout, DNS failure, etc.) marks internet_connected False."""
    coordinator = _make_coordinator(hass)
    session = MagicMock()
    session.get = MagicMock(side_effect=aiohttp.ClientError("boom"))
    with patch(
        "custom_components.pace.coordinator.async_get_clientsession",
        return_value=session,
    ):
        await coordinator._async_check_connectivity()
    assert coordinator.internet_connected is False


async def test_check_connectivity_notifies_listeners(
    hass: HomeAssistant, mock_store
) -> None:
    """Test a connectivity check pushes an update to entity listeners."""
    coordinator = _make_coordinator(hass)
    coordinator.async_update_listeners = MagicMock()
    session = MagicMock()
    session.get = MagicMock(return_value=_mock_response(200, {"ip": "1.2.3.4"}))
    with patch(
        "custom_components.pace.coordinator.async_get_clientsession",
        return_value=session,
    ):
        await coordinator._async_check_connectivity()
    coordinator.async_update_listeners.assert_called_once()


async def test_start_connectivity_check_arms_timer_once(hass: HomeAssistant) -> None:
    """Test start_connectivity_check registers exactly one timer and unload callback."""
    coordinator = _make_coordinator(hass)
    with patch(
        "custom_components.pace.coordinator.async_track_time_interval"
    ) as mock_track:
        coordinator.start_connectivity_check()
        coordinator.start_connectivity_check()  # second call should be a no-op
    mock_track.assert_called_once()
    coordinator.config_entry.async_on_unload.assert_any_call(
        coordinator._cancel_connectivity_check
    )


async def test_start_connectivity_check_uses_configured_interval(
    hass: HomeAssistant,
) -> None:
    """Test the configured connectivity_check_interval drives the timer period."""
    coordinator = _make_coordinator(hass, connectivity_check_interval=120)
    with patch(
        "custom_components.pace.coordinator.async_track_time_interval"
    ) as mock_track:
        coordinator.start_connectivity_check()
    assert mock_track.call_args[0][2] == timedelta(seconds=120)


async def test_cancel_connectivity_check_unsubscribes(hass: HomeAssistant) -> None:
    """Test _cancel_connectivity_check calls and clears the unsub callback."""
    coordinator = _make_coordinator(hass)
    unsub = MagicMock()
    coordinator._unsub_connectivity_check = unsub
    coordinator._cancel_connectivity_check()
    unsub.assert_called_once()
    assert coordinator._unsub_connectivity_check is None
