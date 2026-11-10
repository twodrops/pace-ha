"""Tests for Pace base entity."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.helpers.device_registry import DeviceEntryType

from custom_components.pace.const import DOMAIN
from custom_components.pace.entity import PaceBaseEntity


def _make_entity(
    data=None, last_update_success=True, entry_id="test_id", title="Test",
    backend_type="librespeed", consecutive_failures=0,
):
    """Create a base entity with a mocked coordinator."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success = last_update_success
    coordinator.consecutive_failures = consecutive_failures
    coordinator.config_entry.entry_id = entry_id
    coordinator.entry_title = title
    coordinator.backend_type = backend_type
    description = SensorEntityDescription(key="test_key")
    return PaceBaseEntity(coordinator, description)


def test_unique_id() -> None:
    """Test unique_id format."""
    entity = _make_entity(entry_id="my_entry")
    assert entity.unique_id == "my_entry_test_key"


def test_has_entity_name() -> None:
    """Test has_entity_name is True."""
    entity = _make_entity()
    assert entity._attr_has_entity_name is True


def test_device_info() -> None:
    """Test device_info structure for the default (LibreSpeed) backend."""
    entity = _make_entity(entry_id="eid", title="My Speed Test")
    info = entity.device_info
    assert (DOMAIN, "eid") in info["identifiers"]
    assert info["name"] == "My Speed Test"
    assert info["manufacturer"] == "LibreSpeed"
    assert info["model"] == "LibreSpeed CLI"
    assert info["entry_type"] == DeviceEntryType.SERVICE


def test_device_info_ookla_backend() -> None:
    """Test device_info reflects the Ookla backend when configured."""
    entity = _make_entity(entry_id="eid", backend_type="ookla")
    info = entity.device_info
    assert info["manufacturer"] == "Ookla"
    assert info["model"] == "Speedtest CLI"


def test_available_with_data() -> None:
    """Test entity is available when coordinator has data and no failures."""
    entity = _make_entity(data={"download": 100})
    assert entity.available is True


def test_unavailable_no_data() -> None:
    """Test entity is unavailable when no data."""
    entity = _make_entity(data=None)
    assert entity.available is False


def test_available_below_failure_threshold() -> None:
    """Test entity stays available through a handful of failures, keeping
    the last known-good reading visible (e.g. a backend's own rate
    limiting shouldn't flip entities unavailable on every single attempt).
    """
    entity = _make_entity(data={"download": 100}, consecutive_failures=4)
    assert entity.available is True


def test_unavailable_at_failure_threshold() -> None:
    """Test entity goes unavailable once failures reach the warning threshold."""
    entity = _make_entity(data={"download": 100}, consecutive_failures=5)
    assert entity.available is False
