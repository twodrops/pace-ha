"""Support for Pace button."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PaceConfigEntry
from .const import LOGGER_NAME
from .coordinator import PaceDataUpdateCoordinator
from .entity import PaceBaseEntity

_LOGGER = logging.getLogger(LOGGER_NAME)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PaceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pace button."""
    coordinator = config_entry.runtime_data.coordinator

    async_add_entities([PaceButton(coordinator, config_entry)])


class PaceButton(PaceBaseEntity, ButtonEntity):
    """Implementation of a Pace button."""

    def __init__(
        self,
        coordinator: PaceDataUpdateCoordinator,
        entry: PaceConfigEntry,
    ) -> None:
        """Initialize the button."""
        description = ButtonEntityDescription(
            key="run_test",
            translation_key="run_test",
            name="Run Speed Test",
        )
        super().__init__(coordinator, description)
        self._entry = entry

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Always available (not tied to lock state or last test's
        success/failure) so the button never Unavailable/Available-toggles
        in the Logbook; a press is simply a no-op if already busy.
        """
        return True

    async def async_press(self) -> None:
        """Handle the button press.

        A press while this instance is already running or queued is simply
        a silent no-op instead of the button going Unavailable.
        """
        _LOGGER.info("Manual speed test button pressed")
        if self.coordinator.is_running or self.coordinator.is_waiting:
            _LOGGER.debug("Speed test already in progress or queued, ignoring button press")
            return
        await self.coordinator.async_refresh()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        if self.coordinator.is_running:
            status = "Running test"
        else:
            status = "Ready"

        return {
            "status": status,
            "test_running": self.coordinator.is_running,
            "waiting_in_queue": self.coordinator.is_waiting,
        }
