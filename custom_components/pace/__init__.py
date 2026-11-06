"""The Pace integration."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .backends.librespeed_cli import LibreSpeedCLIBackend
from .backends.ookla_cli import OoklaCLIBackend
from .backends.speedtest_go_cli import SpeedtestGoCLIBackend
from .const import (
    BACKEND_OOKLA,
    BACKEND_SPEEDTEST_GO,
    CONF_AUTO_REGISTER_CARDS,
    CONF_AUTO_UPDATE,
    CONF_BACKEND_TYPE,
    CONF_CONNECTIVITY_CHECK_INTERVAL,
    CONF_CUSTOM_SERVER,
    CONF_FALLBACK_TO_CLOSEST,
    CONF_ISP_DOWNLOAD_SPEED,
    CONF_ISP_UPLOAD_SPEED,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_ID,
    CONF_SKIP_CERT_VERIFY,
    CONF_SOURCE_INTERFACE,
    CONF_SOURCE_IP,
    CONF_START_TIME,
    CONF_TEST_TIMEOUT,
    DEFAULT_AUTO_REGISTER_CARDS,
    DEFAULT_BACKEND_TYPE,
    DEFAULT_CONNECTIVITY_CHECK_INTERVAL,
    DEFAULT_FALLBACK_TO_CLOSEST,
    DEFAULT_TEST_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    FIRST_TEST_DELAY,
    LOGGER_NAME,
    NETWORK_STABILIZATION_DELAY,
)
from .coordinator import PaceDataUpdateCoordinator
from .www_manager import (
    async_register_cards,
    async_register_resources_service,
    async_remove_cards_and_resources,
    async_setup_cards,
)

_LOGGER: Final = logging.getLogger(LOGGER_NAME)

PLATFORMS: Final[list[Platform]] = [
    Platform.SENSOR,
    Platform.BUTTON,
    Platform.BINARY_SENSOR,
]

# Type alias for Pace config entries with runtime data
type PaceConfigEntry = ConfigEntry[PaceRuntimeData]


def _get_backend_class(backend_type: str) -> type:
    """Resolve the CLI backend class for a given backend_type.

    Looks up the class by bare module-global name (not a dict literal built
    at import time) so that tests can `unittest.mock.patch("custom_components.
    pace.LibreSpeedCLIBackend", ...)` etc. and have it take effect here.
    """
    if backend_type == BACKEND_OOKLA:
        return OoklaCLIBackend
    if backend_type == BACKEND_SPEEDTEST_GO:
        return SpeedtestGoCLIBackend
    return LibreSpeedCLIBackend


@dataclass
class PaceRuntimeData:
    """Runtime data for the Pace integration.

    Stores all runtime components needed by the integration,
    following Home Assistant's best practices for ConfigEntry.runtime_data.
    """

    coordinator: PaceDataUpdateCoordinator


def get_config_value(entry: ConfigEntry, key: str, default: Any = None) -> Any:
    """Get config value, preferring options over data.

    Args:
        entry: The config entry to get the value from.
        key: The configuration key to retrieve.
        default: Default value if key not found.

    Returns:
        The configuration value, with options taking precedence over data.
    """
    # Options take precedence over data (user can change these)
    if key in entry.options:
        return entry.options[key]
    # Fall back to data (initial config)
    return entry.data.get(key, default)


async def async_setup_cards_and_resources(
    hass: HomeAssistant, auto_register: bool = True
) -> None:
    """Set up custom Lovelace cards and register resources.

    This function:
    1. Registers services for manual resource registration and removal
    2. If auto_register is True: copies card files to www folder and
       auto-registers resources on startup
    3. If auto_register is False: cleans up card files from www and
       unregisters resources
    """
    try:
        await async_register_resources_service(hass)

        if not auto_register:
            _LOGGER.debug(
                "Automatic card registration is disabled; cleaning up cards and resources"
            )
            await async_remove_cards_and_resources(hass)
            return

        await async_setup_cards(hass)

        async def auto_register_resources(event):
            await async_register_cards(hass)

        if hass.is_running:
            await auto_register_resources(None)
        else:
            hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, auto_register_resources
            )

        _LOGGER.info(
            "Pace cards are ready! Resources will be auto-registered on "
            "startup. Call service 'pace.register_card_resources' to manually register."
        )

    except Exception as e:  # noqa: BLE001 - must not block integration setup
        _LOGGER.error("Failed to set up cards: %s", e)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Pace from a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Config entry for this integration.

    Returns:
        True if setup successful.

    Raises:
        ConfigEntryNotReady: If the CLI backend fails to become available.
    """
    _LOGGER.info("Setting up Pace integration")
    _LOGGER.debug("Entry data: %s", entry.data)
    _LOGGER.debug("Entry options: %s", entry.options)

    # Initialize domain data storage if not already present
    # This creates a dictionary to store integration-specific data
    hass.data.setdefault(DOMAIN, {})

    # Create global test lock if it doesn't exist
    # This ensures only one speed test runs across all instances
    if "test_lock" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["test_lock"] = asyncio.Lock()
        _LOGGER.debug("Created global test lock for Pace")

    # Create the appropriate CLI backend based on configuration. All three
    # backends (LibreSpeed/Ookla/speedtest-go) implement the same interface,
    # so setup never branches beyond picking the class.
    backend_type = get_config_value(entry, CONF_BACKEND_TYPE, DEFAULT_BACKEND_TYPE)
    backend_cls = _get_backend_class(backend_type)

    _LOGGER.info("Using %s backend", backend_type)
    client = backend_cls(hass.config.path(), hass=hass)

    _LOGGER.info("Checking for %s CLI binary...", backend_type)

    # Small delay on first setup to allow network stack to stabilize
    # This helps with DNS resolution issues during HA startup
    if not await client.check_cli_exists():
        _LOGGER.info(
            "CLI not found, will download. Waiting 2 seconds for network to stabilize..."
        )
        await asyncio.sleep(NETWORK_STABILIZATION_DELAY)

    if not await client.ensure_cli_available():
        _LOGGER.error(
            "Failed to set up %s backend - will retry on next restart", backend_type
        )
        raise ConfigEntryNotReady(
            f"Failed to download the {backend_type} CLI binary. This often happens "
            "during startup due to DNS not being ready. The integration will retry "
            "automatically."
        )
    _LOGGER.info("%s CLI is ready", backend_type)

    try:
        coordinator = PaceDataUpdateCoordinator(
            hass,
            client,
            get_config_value(entry, CONF_SERVER_ID),
            get_config_value(entry, CONF_CUSTOM_SERVER),
            get_config_value(entry, CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            get_config_value(entry, CONF_AUTO_UPDATE, True),
            get_config_value(entry, CONF_SKIP_CERT_VERIFY, False),
            backend_type,
            config_entry=entry,
            test_timeout=get_config_value(
                entry, CONF_TEST_TIMEOUT, DEFAULT_TEST_TIMEOUT
            ),
            isp_download_speed=get_config_value(entry, CONF_ISP_DOWNLOAD_SPEED, 0),
            isp_upload_speed=get_config_value(entry, CONF_ISP_UPLOAD_SPEED, 0),
            source_interface=get_config_value(entry, CONF_SOURCE_INTERFACE),
            source_ip=get_config_value(entry, CONF_SOURCE_IP),
            start_time=get_config_value(entry, CONF_START_TIME),
            fallback_to_closest=get_config_value(
                entry, CONF_FALLBACK_TO_CLOSEST, DEFAULT_FALLBACK_TO_CLOSEST
            ),
            connectivity_check_interval=get_config_value(
                entry,
                CONF_CONNECTIVITY_CHECK_INTERVAL,
                DEFAULT_CONNECTIVITY_CHECK_INTERVAL,
            ),
        )

        # Load stored data BEFORE setting up platforms so sensors have data
        await coordinator.async_load_lifetime_data()

        # Lightweight periodic internet-connectivity/public-IP check, fully
        # independent of the (much heavier) speed test cycle above. Run one
        # check now (awaited, not fire-and-forget) so the Internet Connected/
        # Public IP entities aren't stuck on "unknown" right after startup.
        coordinator.start_connectivity_check()
        await coordinator._async_check_connectivity()

        if coordinator.auto_update:
            # Delay first refresh by 60 seconds to avoid lag during setup
            _LOGGER.info("Scheduling first automatic speed test in 60 seconds")

            async def delayed_first_refresh():
                """Delay the first refresh to avoid setup lag."""
                await asyncio.sleep(FIRST_TEST_DELAY)
                _LOGGER.info("Running first automatic speed test")
                await coordinator.async_refresh()

            entry.async_create_background_task(
                hass, delayed_first_refresh(), "pace_first_refresh"
            )
        else:
            _LOGGER.info("Automatic speed tests disabled")

        # Store runtime data in ConfigEntry using the new pattern
        # This replaces the old hass.data[DOMAIN] storage method
        entry.runtime_data = PaceRuntimeData(coordinator=coordinator)

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

        entry.async_on_unload(entry.add_update_listener(async_reload_entry))

        # Set up custom cards and register resources. This is effectively a
        # GLOBAL preference (one www/pace folder, one set of Lovelace
        # resources shared by every Pace entry) - so checking only
        # this entry's own flag would let one entry's toggle being off wipe
        # out cards that another entry just installed, depending on
        # setup/reload order. Keep cards installed if ANY entry wants them.
        any_entry_wants_cards = any(
            get_config_value(e, CONF_AUTO_REGISTER_CARDS, DEFAULT_AUTO_REGISTER_CARDS)
            for e in hass.config_entries.async_entries(DOMAIN)
        )
        await async_setup_cards_and_resources(hass, auto_register=any_entry_wants_cards)

        return True

    except Exception:
        raise


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    This function cleanly unloads the integration by:
    1. Saving lifetime data before unload
    2. Unloading all platforms (sensors, buttons, binary_sensors)
    3. Removing the coordinator from memory

    Args:
        hass: Home Assistant instance.
        entry: Config entry to unload.

    Returns:
        True if unload was successful, False otherwise.
    """
    _LOGGER.info("Unloading Pace integration")

    # Save lifetime data before unloading
    runtime_data: PaceRuntimeData = entry.runtime_data
    if runtime_data.coordinator:
        await runtime_data.coordinator.async_save_lifetime_data()

    # Attempt to unload all platforms associated with this integration
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry.

    Called when the user changes configuration options.
    This will unload and reload the integration with new settings.

    Args:
        hass: Home Assistant instance.
        entry: Config entry to reload.
    """
    _LOGGER.info("Reloading Pace integration due to config change")
    await hass.config_entries.async_reload(entry.entry_id)
