"""Base entity for the Pace integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import BACKEND_DEVICE_INFO, CIRCUIT_BREAKER_WARNING_THRESHOLD, DOMAIN
from .coordinator import PaceDataUpdateCoordinator


class PaceBaseEntity(CoordinatorEntity[PaceDataUpdateCoordinator]):
    """Base entity for the Pace integration.

    All Pace entities should inherit from this base class.
    It provides common functionality including:
    - Device information
    - Entity naming
    - Unique ID generation
    - Coordinator integration
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PaceDataUpdateCoordinator,
        entity_description: EntityDescription,
    ) -> None:
        """Initialize the base entity.

        Args:
            coordinator: The data update coordinator
            entity_description: The entity description
        """
        super().__init__(coordinator)
        self.entity_description = entity_description

        # Generate unique ID based on config entry and entity key
        config_entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{config_entry_id}_{entity_description.key}"

        # Force the entity name (and therefore its entity_id slug) to the
        # fixed English string on entity_description.name, taking priority
        # over translation_key-based localization. This keeps entity_ids
        # stable across all HA languages, matching dashboard card defaults.
        if isinstance(entity_description.name, str):
            self._attr_name = entity_description.name

        # Manufacturer/model/URL reflect whichever CLI backend this config
        # entry actually runs, not a single hardcoded brand.
        device_info = BACKEND_DEVICE_INFO.get(
            coordinator.backend_type, BACKEND_DEVICE_INFO["librespeed"]
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config_entry_id)},
            name=coordinator.entry_title,
            manufacturer=device_info["manufacturer"],
            model=device_info["model"],
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=device_info["configuration_url"],
        )

    @property
    def available(self) -> bool:
        """Return if entity is available.

        Available once there's ever been a successful test, tolerating up
        to CIRCUIT_BREAKER_WARNING_THRESHOLD - 1 consecutive failures
        before going unavailable - a backend's own rate limiting (e.g.
        Ookla) or a single transient hiccup no longer flips entities
        unavailable on every failed attempt; the last known reading stays
        visible until failures actually pile up, at the same point a
        repair issue would already warn about it.
        """
        if self.coordinator.data is None:
            return False
        return self.coordinator.consecutive_failures < CIRCUIT_BREAKER_WARNING_THRESHOLD
