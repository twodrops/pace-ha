"""Support for Pace sensors."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfDataRate, UnitOfInformation, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PaceConfigEntry
from .const import (
    ATTR_BYTES_RECEIVED,
    ATTR_BYTES_SENT,
    ATTR_DOWNLOAD,
    ATTR_DOWNLOAD_COMPLIANCE,
    ATTR_JITTER,
    ATTR_LIFETIME_DOWNLOAD,
    ATTR_LIFETIME_UPLOAD,
    ATTR_PING,
    ATTR_SERVER_LOCATION,
    ATTR_SERVER_NAME,
    ATTR_SERVER_SPONSOR,
    ATTR_TIMESTAMP,
    ATTR_UPLOAD,
    ATTR_UPLOAD_COMPLIANCE,
    BACKENDS,
    LOGGER_NAME,
)
from .coordinator import PaceDataUpdateCoordinator
from .entity import PaceBaseEntity

_LOGGER = logging.getLogger(LOGGER_NAME)


@dataclass(frozen=True, kw_only=True)
class PaceSensorEntityDescription(SensorEntityDescription):
    """Describes Pace sensor entity.

    Extends the base SensorEntityDescription with an optional
    attribute field to map sensor values to specific data attributes
    from the coordinator's data dictionary.
    """

    # The attribute key in coordinator data to extract the value from
    # If None, the sensor's key is used as the attribute name
    attribute: str | None = None


# Define all available sensor types with their configurations
# Each sensor maps to a specific metric from the speed test results
SENSOR_TYPES: tuple[PaceSensorEntityDescription, ...] = (
    PaceSensorEntityDescription(
        key="download",
        translation_key="download",
        name="Download Speed",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_DOWNLOAD,
    ),
    PaceSensorEntityDescription(
        key="upload",
        translation_key="upload",
        name="Upload Speed",
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        device_class=SensorDeviceClass.DATA_RATE,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_UPLOAD,
    ),
    PaceSensorEntityDescription(
        key="ping",
        translation_key="ping",
        name="Ping",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_PING,
    ),
    PaceSensorEntityDescription(
        key="jitter",
        translation_key="jitter",
        name="Jitter",
        native_unit_of_measurement=UnitOfTime.MILLISECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_JITTER,
    ),
    PaceSensorEntityDescription(
        key="data_downloaded",
        translation_key="data_downloaded",
        name="Test Data Downloaded",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_BYTES_RECEIVED,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PaceSensorEntityDescription(
        key="data_uploaded",
        translation_key="data_uploaded",
        name="Test Data Uploaded",
        native_unit_of_measurement=UnitOfInformation.MEGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_BYTES_SENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PaceSensorEntityDescription(
        key="server_name",
        translation_key="server_name",
        name="Server Name",
        attribute=ATTR_SERVER_NAME,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PaceSensorEntityDescription(
        key="backend",
        translation_key="backend",
        name="Backend",
        device_class=SensorDeviceClass.ENUM,
        options=list(BACKENDS),
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PaceSensorEntityDescription(
        key="last_test",
        translation_key="last_test",
        name="Last Test Time",
        device_class=SensorDeviceClass.TIMESTAMP,
        attribute=ATTR_TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PaceSensorEntityDescription(
        key="lifetime_download",
        translation_key="lifetime_download",
        name="Lifetime Data Downloaded",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        attribute=ATTR_LIFETIME_DOWNLOAD,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PaceSensorEntityDescription(
        key="lifetime_upload",
        translation_key="lifetime_upload",
        name="Lifetime Data Uploaded",
        native_unit_of_measurement=UnitOfInformation.GIGABYTES,
        device_class=SensorDeviceClass.DATA_SIZE,
        state_class=SensorStateClass.TOTAL_INCREASING,
        attribute=ATTR_LIFETIME_UPLOAD,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    PaceSensorEntityDescription(
        key="download_compliance",
        translation_key="download_compliance",
        name="Download Plan Compliance",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_DOWNLOAD_COMPLIANCE,
    ),
    PaceSensorEntityDescription(
        key="upload_compliance",
        translation_key="upload_compliance",
        name="Upload Plan Compliance",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        attribute=ATTR_UPLOAD_COMPLIANCE,
    ),
    PaceSensorEntityDescription(
        key="public_ip",
        translation_key="public_ip",
        name="Public IP Address",
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: PaceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Pace sensors."""
    coordinator = config_entry.runtime_data.coordinator

    async_add_entities(
        PaceSensor(coordinator, description, config_entry)
        for description in SENSOR_TYPES
    )


class PaceSensor(PaceBaseEntity, SensorEntity):
    """Implementation of a Pace sensor."""

    entity_description: PaceSensorEntityDescription

    def __init__(
        self,
        coordinator: PaceDataUpdateCoordinator,
        description: PaceSensorEntityDescription,
        entry: PaceConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        # Base class handles coordinator, unique_id, and device_info
        super().__init__(coordinator, description)
        self._entry = entry

    @property
    def native_value(self) -> Any:
        """Return the state of the sensor."""
        # Backend is fixed per config entry, not test data - always available.
        if self.entity_description.key == "backend":
            return self.coordinator.backend_type

        # Updated by the lightweight connectivity check, not by test data.
        if self.entity_description.key == "public_ip":
            return self.coordinator.public_ip

        if not self.coordinator.data:
            return None

        if self.entity_description.attribute:
            value = self.coordinator.data.get(self.entity_description.attribute)

            # Convert bytes to megabytes for data size sensors
            if self.entity_description.key in ("data_downloaded", "data_uploaded"):
                if value is not None:
                    return round(value / 1_000_000, 2)  # Convert bytes to MB

            # Lifetime data is accumulated via float division (bytes / 1e9),
            # which leaves long binary-float tails (e.g. 7 decimal places) if
            # not rounded before being shown as the sensor's state.
            if self.entity_description.key in ("lifetime_download", "lifetime_upload"):
                if value is not None:
                    return round(value, 2)

            return value

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        # These are coordinator config, not test data, so expose them even
        # before the first test has run (the card gauge reads this to
        # auto-scale its max to the user's rated plan speed).
        if self.entity_description.key == "download_compliance":
            return {
                "isp_rated_speed": self.coordinator.isp_download_speed,
            }
        if self.entity_description.key == "upload_compliance":
            return {
                "isp_rated_speed": self.coordinator.isp_upload_speed,
            }

        if not self.coordinator.data:
            return {}

        if self.entity_description.key == "download":
            return {
                "bytes_received": self.coordinator.data.get(ATTR_BYTES_RECEIVED, 0),
            }
        if self.entity_description.key == "upload":
            return {
                "bytes_sent": self.coordinator.data.get(ATTR_BYTES_SENT, 0),
            }
        if self.entity_description.key == "server_name":
            return {
                "location": self.coordinator.data.get(ATTR_SERVER_LOCATION, "Unknown"),
                "sponsor": self.coordinator.data.get(ATTR_SERVER_SPONSOR, "Unknown"),
                "backend": self.coordinator.backend_type,
            }

        return {}

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.async_write_ha_state()
