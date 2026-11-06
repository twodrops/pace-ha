"""Tests for Pace binary sensor platform."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.pace.exceptions import SpeedTestError

ENTITY_ID = "binary_sensor.pace_manual_speed_test_running"


async def test_binary_sensor_entity_created(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test binary sensor is created through HA setup pipeline."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state is not None


async def test_initial_state_off(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test binary sensor is off when no test is running."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.state == "off"


async def test_extra_attributes(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test binary sensor extra state attributes."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.attributes["this_instance_running"] is False
    assert state.attributes["this_instance_waiting"] is False
    assert state.attributes["instance_name"] == "Pace (Manual)"


async def test_available_without_data(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
) -> None:
    """Test binary sensor stays available even with no stored data."""
    with patch(
        "custom_components.pace.coordinator.Store",
        autospec=True,
    ) as mock_store_cls:
        store = mock_store_cls.return_value
        store.async_load = AsyncMock(return_value=None)
        store.async_save = AsyncMock()

        await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
        await hass.async_block_till_done()

    # Binary sensor overrides available to always return True
    state = hass.states.get(ENTITY_ID)
    assert state.state == "off"  # Not "unavailable"


INTERNET_ENTITY_ID = "binary_sensor.pace_manual_internet_connected"


async def test_internet_connected_entity_created(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test the Internet Connected binary sensor is created."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(INTERNET_ENTITY_ID)
    assert state is not None


async def test_internet_connected_has_definite_state_after_setup(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test it's no longer stuck on 'unknown' right after setup.

    async_setup_entry() awaits one connectivity check eagerly (not just the
    30s-later periodic one), so the entity has a real on/off state as soon
    as setup completes instead of waiting for the first interval tick.
    """
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(INTERNET_ENTITY_ID)
    assert state.state in ("on", "off")


async def test_internet_connected_reflects_coordinator_state(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test the sensor reflects coordinator.internet_connected, independent of speed test data."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_no_auto.runtime_data.coordinator

    coordinator.internet_connected = True
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(INTERNET_ENTITY_ID).state == "on"

    coordinator.internet_connected = False
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get(INTERNET_ENTITY_ID).state == "off"


async def test_internet_connected_available_without_speed_test_data(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
) -> None:
    """Test it stays available even when there's no stored speed test data."""
    with patch(
        "custom_components.pace.coordinator.Store",
        autospec=True,
    ) as mock_store_cls:
        store = mock_store_cls.return_value
        store.async_load = AsyncMock(return_value=None)
        store.async_save = AsyncMock()

        await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
        await hass.async_block_till_done()

    state = hass.states.get(INTERNET_ENTITY_ID)
    assert state.state != "unavailable"


async def test_device_class(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test binary sensor has correct device class."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_ID)
    assert state.attributes["device_class"] == "running"


async def test_stays_available_after_failed_update(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test binary sensor stays available even after coordinator failure."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    # Make speed test fail
    mock_native_client.run_speed_test.side_effect = SpeedTestError("Connection lost")
    coordinator = mock_config_entry_no_auto.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    # Binary sensor should still be available (overrides base entity)
    state = hass.states.get(ENTITY_ID)
    assert state.state == "off"  # Not "unavailable"


async def test_turns_on_when_lock_held(
    hass: HomeAssistant,
    mock_config_entry_no_auto: MockConfigEntry,
    mock_native_client: AsyncMock,
    mock_store: AsyncMock,
) -> None:
    """Test binary sensor turns on when global lock is acquired."""
    await hass.config_entries.async_setup(mock_config_entry_no_auto.entry_id)
    await hass.async_block_till_done()

    coordinator = mock_config_entry_no_auto.runtime_data.coordinator

    # Simulate a test running
    await coordinator.global_lock.acquire()
    try:
        coordinator.async_update_listeners()
        await hass.async_block_till_done()

        state = hass.states.get(ENTITY_ID)
        assert state.state == "on"
    finally:
        coordinator.global_lock.release()
