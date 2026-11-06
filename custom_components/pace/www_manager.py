"""Manager for Lovelace card resources."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import stat

from homeassistant.components.lovelace import DOMAIN as LOVELACE_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN, SERVICE_REGISTER_CARD_RESOURCES, SERVICE_REMOVE_CARD_RESOURCES

_LOGGER = logging.getLogger(__name__)

VERSION = json.loads(
    (Path(__file__).with_name("manifest.json")).read_text(encoding="utf-8")
)["version"]

# List of cards to manage
CARDS = [
    "pace-minimal.js",
    "pace-compact.js",
    "pace-dashboard.js",
]

CARD_ASSETS = [*CARDS, "pace-card-utils.js"]

WWW_SOURCE_DIR = Path(__file__).parent / "www"


async def async_setup_cards(hass: HomeAssistant) -> bool:
    """Set up the custom cards by copying to www folder.

    This ensures cards are accessible at /local/pace/
    """
    try:
        www_dir = Path(hass.config.path("www"))
        target_dir = www_dir / "pace"

        if not www_dir.exists():
            _LOGGER.info("Creating www directory")
            await hass.async_add_executor_job(www_dir.mkdir)

        if not target_dir.exists():
            await hass.async_add_executor_job(target_dir.mkdir)

        copied_count = 0
        for card in CARD_ASSETS:
            source = WWW_SOURCE_DIR / card
            target = target_dir / card

            if source.exists():
                await hass.async_add_executor_job(shutil.copy2, source, target)

                # Ensure file is world-readable (644) so webserver can serve it
                def set_permissions(target_path: Path = target) -> None:
                    try:
                        os.chmod(
                            target_path,
                            stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH,
                        )
                    except OSError as e:
                        _LOGGER.warning(
                            "Could not set permissions for %s: %s", target_path, e
                        )

                await hass.async_add_executor_job(set_permissions)

                copied_count += 1

        _LOGGER.debug(
            "Pace cards installed to www folder (%d files)", copied_count
        )
        return True

    except Exception as e:  # noqa: BLE001 - must not block integration setup
        _LOGGER.error("Failed to set up cards: %s", e)
        return False


async def async_remove_cards_and_resources(hass: HomeAssistant) -> None:
    """Remove cards from www folder and unregister resources."""
    try:
        www_dir = Path(hass.config.path("www"))
        target_dir = www_dir / "pace"

        if target_dir.exists():
            _LOGGER.info("Removing Pace cards from www directory")
            await hass.async_add_executor_job(shutil.rmtree, target_dir)

        lovelace = hass.data.get(LOVELACE_DOMAIN)
        if not lovelace:
            return

        if not getattr(lovelace, "resources", None) or not lovelace.resources.loaded:
            _LOGGER.debug(
                "Lovelace resources not loaded for removal, retrying in 5 seconds"
            )
            async_call_later(
                hass,
                5,
                lambda _: hass.async_create_task(
                    async_remove_cards_and_resources(hass)
                ),
            )
            return

        resources = lovelace.resources

        for card in CARDS:
            base_url = f"/local/pace/{card}"

            found_resource = None
            for resource in resources.async_items():
                if resource["url"].split("?")[0] == base_url:
                    found_resource = resource
                    break

            if found_resource:
                _LOGGER.info("Unregistering Lovelace resource: %s", base_url)
                await resources.async_delete_item(found_resource["id"])

    except Exception as e:  # noqa: BLE001 - must not block integration setup
        _LOGGER.error("Failed to remove cards/resources: %s", e)


async def async_register_cards(hass: HomeAssistant) -> None:
    """Register Lovelace resources safely."""
    lovelace = hass.data.get(LOVELACE_DOMAIN)

    if not lovelace:
        _LOGGER.debug("Lovelace not loaded, skipping resource registration")
        return

    if not getattr(lovelace, "resources", None) or not lovelace.resources.loaded:
        _LOGGER.debug("Lovelace resources not loaded, retrying in 5 seconds")
        async_call_later(
            hass, 5, lambda _: hass.async_create_task(async_register_cards(hass))
        )
        return

    resources = lovelace.resources

    for card in CARDS:
        base_url = f"/local/pace/{card}"
        full_url = f"{base_url}?v={VERSION}"

        found_resource = None
        for resource in resources.async_items():
            if resource["url"].split("?")[0] == base_url:
                found_resource = resource
                break

        if found_resource:
            if found_resource["url"] != full_url:
                _LOGGER.info(
                    "Updating Lovelace resource %s to version %s", base_url, VERSION
                )
                try:
                    await resources.async_update_item(
                        found_resource["id"],
                        {"res_type": "module", "url": full_url},
                    )
                except Exception as e:  # noqa: BLE001 - one bad card must not block the rest
                    _LOGGER.error("Failed to update resource %s: %s", base_url, e)
        else:
            _LOGGER.info("Auto-registering Lovelace resource: %s", full_url)
            try:
                await resources.async_create_item(
                    {"res_type": "module", "url": full_url}
                )
            except Exception as e:  # noqa: BLE001 - one bad card must not block the rest
                _LOGGER.error("Failed to register %s: %s", full_url, e)


async def async_register_resources_service(hass: HomeAssistant) -> None:
    """Register services to manage Lovelace card resources."""

    async def handle_register_resources(call):
        """Handle manual registration service call."""
        await async_setup_cards(hass)
        await async_register_cards(hass)

    async def handle_remove_resources(call):
        """Handle manual removal service call."""
        await async_remove_cards_and_resources(hass)

    if not hass.services.has_service(DOMAIN, SERVICE_REGISTER_CARD_RESOURCES):
        hass.services.async_register(
            DOMAIN, SERVICE_REGISTER_CARD_RESOURCES, handle_register_resources
        )

    if not hass.services.has_service(DOMAIN, SERVICE_REMOVE_CARD_RESOURCES):
        hass.services.async_register(
            DOMAIN, SERVICE_REMOVE_CARD_RESOURCES, handle_remove_resources
        )


def get_card_info() -> list[dict[str, str]]:
    """Get information about available cards."""
    return [
        {
            "name": "Pace - Minimal",
            "type": "custom:pace-minimal",
            "description": "Clean design with large typography",
            "file": "pace-minimal.js",
        },
        {
            "name": "Pace - Compact",
            "type": "custom:pace-compact",
            "description": "Small single-line card",
            "file": "pace-compact.js",
        },
        {
            "name": "Pace - Dashboard",
            "type": "custom:pace-dashboard",
            "description": "Full interface with radial gauges and history charts",
            "file": "pace-dashboard.js",
        },
    ]
