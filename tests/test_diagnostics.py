"""Tests for Pace diagnostics."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pace import PaceRuntimeData
from custom_components.pace.const import DOMAIN
from custom_components.pace.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import MOCK_PARSED_RESULT


def _make_entry_with_coordinator(hass, data=None, backend_type="librespeed", auto_update=True):
    """Create a config entry with mock coordinator for diagnostics."""
    coordinator = MagicMock()
    coordinator.data = deepcopy(data) if data else None
    coordinator.backend_type = backend_type
    coordinator.auto_update = auto_update
    coordinator.is_running = False
    coordinator.last_update_success = True
    coordinator.last_exception = None
    if auto_update:
        from datetime import timedelta
        coordinator.update_interval = timedelta(minutes=60)
    else:
        coordinator.update_interval = None

    client = AsyncMock()
    client.cli_path = "/config/custom_components/pace/bin/librespeed/librespeed-cli"
    coordinator.client = client

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"backend_type": backend_type, "auto_update": auto_update},
        unique_id="diag_test",
    )
    entry.add_to_hass(hass)
    entry.runtime_data = PaceRuntimeData(coordinator=coordinator)
    return entry


async def test_diagnostics_with_data(hass: HomeAssistant) -> None:
    """Test diagnostics includes all sections with data."""
    entry = _make_entry_with_coordinator(hass, data=MOCK_PARSED_RESULT)
    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "entry" in result
    assert "coordinator" in result
    assert "last_test" in result
    assert "cli_info" in result
    assert "platform_info" in result
    assert result["last_test"] is not None
    assert result["last_test"]["download_speed"] == 250.50


async def test_diagnostics_without_data(hass: HomeAssistant) -> None:
    """Test diagnostics when no test data available."""
    entry = _make_entry_with_coordinator(hass, data=None)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["last_test"] is None


async def test_diagnostics_cli_backend(hass: HomeAssistant) -> None:
    """Test Ookla backend diagnostics info."""
    entry = _make_entry_with_coordinator(hass, backend_type="ookla")
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["cli_info"]["backend"] == "ookla"


async def test_diagnostics_native_backend(hass: HomeAssistant) -> None:
    """Test LibreSpeed backend diagnostics info."""
    entry = _make_entry_with_coordinator(hass, backend_type="librespeed")
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["cli_info"]["backend"] == "librespeed"


async def test_diagnostics_platform_info(hass: HomeAssistant) -> None:
    """Test platform info is included."""
    entry = _make_entry_with_coordinator(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert "platform" in result["platform_info"]
    assert "python_version" in result["platform_info"]


async def test_diagnostics_no_auto_update(hass: HomeAssistant) -> None:
    """Test scan_interval is None when auto_update disabled."""
    entry = _make_entry_with_coordinator(hass, auto_update=False)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["coordinator"]["scan_interval"] is None
