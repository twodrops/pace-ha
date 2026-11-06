"""Config flow for the Pace integration.

This module handles the configuration flow for the Pace integration,
including initial setup and options management. It provides a user-friendly
wizard for configuring speed test parameters, server selection, and backend
choices.

Key Features:
- Automatic server detection and listing (LibreSpeed backend only)
- Custom server URL support with SSL verification options (LibreSpeed and
  speedtest-go backends only - Ookla has no self-hosted server concept)
- Backend selection (LibreSpeed CLI, Ookla CLI, or speedtest-go CLI)
- Options flow for reconfiguration after setup
- Comprehensive validation and error handling
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Any
from urllib.parse import urlparse

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector

from .backends.librespeed_cli import LibreSpeedCLIBackend, fetch_server_list
from .backends.ookla_cli import OoklaCLIBackend
from .backends.speedtest_go_cli import SpeedtestGoCLIBackend
from .const import (
    BACKEND_LIBRESPEED,
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
    CUSTOM_SERVER_CAPABLE_BACKENDS,
    DEFAULT_AUTO_REGISTER_CARDS,
    DEFAULT_BACKEND_TYPE,
    DEFAULT_CONNECTIVITY_CHECK_INTERVAL,
    DEFAULT_FALLBACK_TO_CLOSEST,
    DEFAULT_ISP_SPEED,
    DEFAULT_TEST_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    LOGGER_NAME,
    MAX_CONNECTIVITY_CHECK_INTERVAL,
    MAX_ISP_SPEED,
    MAX_SCAN_INTERVAL,
    MAX_SERVER_ID,
    MAX_TEST_TIMEOUT,
    MIN_CONNECTIVITY_CHECK_INTERVAL,
    MIN_ISP_SPEED,
    MIN_SCAN_INTERVAL,
    MIN_SERVER_ID,
    MIN_TEST_TIMEOUT,
)

_LOGGER = logging.getLogger(LOGGER_NAME)

_BACKEND_LABELS = {
    BACKEND_LIBRESPEED: "LibreSpeed CLI",
    BACKEND_OOKLA: "Ookla CLI",
    BACKEND_SPEEDTEST_GO: "speedtest-go CLI",
}


def _iter_backend_classes():
    """Yield (backend_id, backend_class) pairs, resolved by name at call time.

    Not a dict literal built at import time, so tests can patch e.g.
    "custom_components.pace.config_flow.LibreSpeedCLIBackend" and have
    it take effect here.
    """
    yield BACKEND_LIBRESPEED, LibreSpeedCLIBackend
    yield BACKEND_OOKLA, OoklaCLIBackend
    yield BACKEND_SPEEDTEST_GO, SpeedtestGoCLIBackend


async def get_server_list(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Get the list of available servers for the "pick from list" option.

    Note: this is always the LibreSpeed public server list - server IDs are
    backend-specific, so this list is only meaningful when the LibreSpeed
    backend is selected. Ookla/speedtest-go users should use "Automatic" or
    know their own server ID.
    """
    return await fetch_server_list(hass)


def _parse_server_selection(server_selection: str) -> tuple[int | None, str | None]:
    """Parse server selection and return server_id and custom_server.

    Args:
        server_selection: The selected server string ("automatic", "custom", or server ID as string)

    Returns:
        Tuple of (server_id, custom_server) where one is always None
    """
    if server_selection == "automatic":
        return None, None
    if server_selection == "custom":
        # Custom server will be handled in next step
        return None, None
    # Try to parse server ID as integer with bounds checking
    try:
        server_id = int(server_selection)
    except (ValueError, IndexError) as e:
        _LOGGER.error("Failed to parse server selection '%s': %s", server_selection, e)
        return None, None

    # Validate server ID is within reasonable bounds (0-10000)
    if server_id < MIN_SERVER_ID or server_id > MAX_SERVER_ID:
        _LOGGER.error(
            "Invalid server ID: %d (must be %d-%d)",
            server_id,
            MIN_SERVER_ID,
            MAX_SERVER_ID,
        )
        return None, None
    return server_id, None


def _validate_ip_field(value: str) -> str:
    """Validate an optional source IP field (an empty string is allowed)."""
    value = (value or "").strip()
    if not value:
        return value
    try:
        ipaddress.ip_address(value)
    except ValueError as err:
        raise vol.Invalid("invalid_source_ip") from err
    return value


def _minutes_to_duration_dict(minutes: int) -> dict[str, int]:
    """Convert an integer number of minutes into a DurationSelector dict.

    Idempotent: if already given a duration dict (e.g. a stale/manually
    edited config), it's returned unchanged.
    """
    if isinstance(minutes, dict):
        return minutes
    total_minutes = int(minutes)
    hours, remainder_minutes = divmod(total_minutes, 60)
    return {"hours": hours, "minutes": remainder_minutes, "seconds": 0}


def _duration_dict_to_minutes(duration: Any) -> int:
    """Convert a DurationSelector dict back into an integer number of minutes.

    Falls back to treating the value as already-a-number for backwards
    compatibility with any stored config predating the DurationSelector.
    """
    if isinstance(duration, dict):
        days = duration.get("days", 0) or 0
        hours = duration.get("hours", 0) or 0
        minutes = duration.get("minutes", 0) or 0
        seconds = duration.get("seconds", 0) or 0
        total_minutes = days * 24 * 60 + hours * 60 + minutes + seconds / 60
        return max(1, int(round(total_minutes)))
    return int(duration)


def _create_custom_server_data(
    custom_url: str, skip_cert_verify: bool, base_input: dict[str, Any]
) -> dict[str, Any]:
    """Create configuration data for custom server.

    Args:
        custom_url: The custom server URL
        skip_cert_verify: Whether to skip certificate verification
        base_input: Base user input containing auto_update, scan_interval, backend_type

    Returns:
        Complete configuration data dictionary
    """
    return {
        CONF_SERVER_ID: None,
        CONF_CUSTOM_SERVER: custom_url,
        CONF_SKIP_CERT_VERIFY: skip_cert_verify,
        CONF_AUTO_UPDATE: base_input.get(CONF_AUTO_UPDATE, True),
        CONF_SCAN_INTERVAL: _duration_dict_to_minutes(
            base_input.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        ),
        CONF_BACKEND_TYPE: base_input.get(CONF_BACKEND_TYPE, DEFAULT_BACKEND_TYPE),
        CONF_ISP_DOWNLOAD_SPEED: base_input.get(
            CONF_ISP_DOWNLOAD_SPEED, DEFAULT_ISP_SPEED
        ),
        CONF_ISP_UPLOAD_SPEED: base_input.get(
            CONF_ISP_UPLOAD_SPEED, DEFAULT_ISP_SPEED
        ),
        CONF_AUTO_REGISTER_CARDS: base_input.get(
            CONF_AUTO_REGISTER_CARDS, DEFAULT_AUTO_REGISTER_CARDS
        ),
        CONF_SOURCE_INTERFACE: (base_input.get(CONF_SOURCE_INTERFACE) or "").strip()
        or None,
        CONF_SOURCE_IP: (base_input.get(CONF_SOURCE_IP) or "").strip() or None,
        CONF_START_TIME: (base_input.get(CONF_START_TIME) or "").strip() or None,
        CONF_FALLBACK_TO_CLOSEST: base_input.get(
            CONF_FALLBACK_TO_CLOSEST, DEFAULT_FALLBACK_TO_CLOSEST
        ),
    }


def _build_backend_schema(hass, config: dict[str, Any] | None = None) -> vol.Schema:
    """Build the first-step schema: backend choice only.

    Kept as its own step (rather than bundled with server selection) so the
    server dropdown in the next step can be reliably filtered by the
    already-submitted backend - HA's data_entry_flow forms aren't reactive,
    so a single combined form can't update the server list live when the
    backend dropdown changes in the browser.
    """
    if config is None:
        config = {}

    # Offer every backend whose CLI has a build for this platform.
    backend_options = []
    for backend_id, backend_cls in _iter_backend_classes():
        if backend_cls(hass.config.path()).is_cli_supported():
            backend_options.append(
                {"value": backend_id, "label": _BACKEND_LABELS[backend_id]}
            )
    if not backend_options:
        # Always offer at least one option even on an unsupported platform,
        # so the form doesn't crash; setup will fail with a clear error later.
        backend_options.append(
            {"value": BACKEND_LIBRESPEED, "label": _BACKEND_LABELS[BACKEND_LIBRESPEED]}
        )

    return vol.Schema(
        {
            vol.Required(
                CONF_BACKEND_TYPE,
                default=config.get(CONF_BACKEND_TYPE, DEFAULT_BACKEND_TYPE),
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=backend_options,
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
        }
    )


def _build_server_schema(
    servers: list[dict[str, Any]], config: dict[str, Any] | None = None
) -> vol.Schema:
    """Build the second-step schema: server selection + all other settings.

    `config` must include CONF_BACKEND_TYPE (already chosen in step one) so
    the server dropdown is filtered correctly for that backend.
    """
    if config is None:
        config = {}

    current_backend = config.get(CONF_BACKEND_TYPE, DEFAULT_BACKEND_TYPE)

    server_options = [{"value": "automatic", "label": "Automatic"}]
    if current_backend == BACKEND_LIBRESPEED:
        server_options.extend(
            [
                {
                    "value": str(server["id"]),
                    "label": f"{server['name']} (ID: {server['id']})",
                }
                for server in servers
            ]
        )
    if current_backend in CUSTOM_SERVER_CAPABLE_BACKENDS:
        server_options.append({"value": "custom", "label": "Custom Server"})

    schema = {
        vol.Required(
            "server_selection",
            default=config.get("server_selection", "automatic"),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=server_options,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            CONF_AUTO_UPDATE,
            default=config.get(CONF_AUTO_UPDATE, True),
        ): bool,
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=_minutes_to_duration_dict(
                config.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL)
            ),
        ): selector.DurationSelector(
            selector.DurationSelectorConfig(enable_day=False, allow_negative=False)
        ),
    }

    # A blank default breaks TimeSelector validation on submit (an empty
    # string isn't a valid time), so only set a default when a real value
    # already exists - otherwise the key is simply absent if left untouched.
    # Inserted right after scan_interval so it appears next to it in the UI.
    existing_start_time = config.get(CONF_START_TIME)
    if existing_start_time:
        schema[vol.Optional(CONF_START_TIME, default=existing_start_time)] = (
            selector.TimeSelector()
        )
    else:
        schema[vol.Optional(CONF_START_TIME)] = selector.TimeSelector()

    schema.update(
        {
            vol.Required(
                CONF_TEST_TIMEOUT,
                default=config.get(CONF_TEST_TIMEOUT, DEFAULT_TEST_TIMEOUT),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_TEST_TIMEOUT,
                    max=MAX_TEST_TIMEOUT,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_CONNECTIVITY_CHECK_INTERVAL,
                default=config.get(
                    CONF_CONNECTIVITY_CHECK_INTERVAL,
                    DEFAULT_CONNECTIVITY_CHECK_INTERVAL,
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_CONNECTIVITY_CHECK_INTERVAL,
                    max=MAX_CONNECTIVITY_CHECK_INTERVAL,
                    unit_of_measurement="seconds",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_SOURCE_INTERFACE,
                default=config.get(CONF_SOURCE_INTERFACE) or "",
            ): str,
            vol.Optional(
                CONF_SOURCE_IP,
                default=config.get(CONF_SOURCE_IP) or "",
            ): str,
            vol.Required(
                CONF_FALLBACK_TO_CLOSEST,
                default=config.get(
                    CONF_FALLBACK_TO_CLOSEST, DEFAULT_FALLBACK_TO_CLOSEST
                ),
            ): bool,
            vol.Optional(
                CONF_ISP_DOWNLOAD_SPEED,
                default=config.get(CONF_ISP_DOWNLOAD_SPEED, DEFAULT_ISP_SPEED),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_ISP_SPEED,
                    max=MAX_ISP_SPEED,
                    unit_of_measurement="Mbit/s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Optional(
                CONF_ISP_UPLOAD_SPEED,
                default=config.get(CONF_ISP_UPLOAD_SPEED, DEFAULT_ISP_SPEED),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=MIN_ISP_SPEED,
                    max=MAX_ISP_SPEED,
                    unit_of_measurement="Mbit/s",
                    mode=selector.NumberSelectorMode.BOX,
                )
            ),
            vol.Required(
                CONF_AUTO_REGISTER_CARDS,
                default=config.get(
                    CONF_AUTO_REGISTER_CARDS, DEFAULT_AUTO_REGISTER_CARDS
                ),
            ): bool,
        }
    )

    return vol.Schema(schema)


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Pace."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._servers: list[dict[str, Any]] = []
        self._backend_type: str = DEFAULT_BACKEND_TYPE

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step: backend choice only."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=_build_backend_schema(self.hass),
            )

        self._backend_type = user_input.get(CONF_BACKEND_TYPE, DEFAULT_BACKEND_TYPE)
        self._servers = await get_server_list(self.hass)
        return await self.async_step_server()

    async def async_step_server(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle server selection and the rest of the settings."""
        if user_input is None:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(
                    {CONF_BACKEND_TYPE: self._backend_type}
                ),
            )

        user_input[CONF_BACKEND_TYPE] = self._backend_type

        # Process server selection first to generate unique ID
        server_selection = user_input.pop("server_selection", "automatic")

        # Ookla has no self-hosted/custom-server concept - reject early with
        # a clear error instead of silently ignoring the choice.
        if server_selection == "custom" and self._backend_type not in CUSTOM_SERVER_CAPABLE_BACKENDS:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={"base": "custom_server_not_supported"},
            )

        # A specific server ID only makes sense for the LibreSpeed backend -
        # the list shown is always LibreSpeed's public server list. The
        # dropdown itself already hides this option for other backends, but
        # keep this as a safety net for scripted/automation-driven flows.
        if server_selection not in ("automatic", "custom") and self._backend_type != BACKEND_LIBRESPEED:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={"server_selection": "server_id_requires_librespeed"},
            )

        scan_interval_minutes = _duration_dict_to_minutes(
            user_input.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        if not MIN_SCAN_INTERVAL <= scan_interval_minutes <= MAX_SCAN_INTERVAL:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={CONF_SCAN_INTERVAL: "invalid_scan_interval"},
            )

        try:
            _validate_ip_field(user_input.get(CONF_SOURCE_IP, ""))
        except vol.Invalid:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={CONF_SOURCE_IP: "invalid_source_ip"},
            )

        # Store settings temporarily
        self._user_input = user_input
        self._server_selection = server_selection

        # If custom server is selected, show custom URL form
        if server_selection == "custom":
            return await self.async_step_custom_server()

        # Parse the server selection using helper function
        server_id, custom_server = _parse_server_selection(server_selection)
        data = {
            CONF_SERVER_ID: server_id,
            CONF_CUSTOM_SERVER: custom_server,
        }

        data[CONF_AUTO_UPDATE] = user_input.get(CONF_AUTO_UPDATE, True)
        data[CONF_SCAN_INTERVAL] = scan_interval_minutes
        data[CONF_START_TIME] = (user_input.get(CONF_START_TIME) or "").strip() or None
        data[CONF_BACKEND_TYPE] = self._backend_type
        data[CONF_ISP_DOWNLOAD_SPEED] = user_input.get(
            CONF_ISP_DOWNLOAD_SPEED, DEFAULT_ISP_SPEED
        )
        data[CONF_ISP_UPLOAD_SPEED] = user_input.get(
            CONF_ISP_UPLOAD_SPEED, DEFAULT_ISP_SPEED
        )
        data[CONF_AUTO_REGISTER_CARDS] = user_input.get(
            CONF_AUTO_REGISTER_CARDS, DEFAULT_AUTO_REGISTER_CARDS
        )
        data[CONF_SOURCE_INTERFACE] = (
            user_input.get(CONF_SOURCE_INTERFACE) or ""
        ).strip() or None
        data[CONF_SOURCE_IP] = (user_input.get(CONF_SOURCE_IP) or "").strip() or None
        data[CONF_FALLBACK_TO_CLOSEST] = user_input.get(
            CONF_FALLBACK_TO_CLOSEST, DEFAULT_FALLBACK_TO_CLOSEST
        )

        # Generate unique ID based on configuration
        # This allows multiple instances with different servers
        if data[CONF_CUSTOM_SERVER]:
            unique_id = f"{DOMAIN}_{data[CONF_CUSTOM_SERVER]}"
            title = "Pace - Custom"
        elif data[CONF_SERVER_ID] is not None:
            unique_id = f"{DOMAIN}_server_{data[CONF_SERVER_ID]}"
            # Try to get server name from the servers list
            server_name = f"Server {data[CONF_SERVER_ID]}"
            for server in self._servers:
                if server["id"] == data[CONF_SERVER_ID]:
                    server_name = server["name"]
                    break
            title = f"Pace - {server_name}"
        else:
            unique_id = f"{DOMAIN}_automatic"
            title = "Pace (Automatic)"

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=title,
            data=data,
        )

    async def async_step_custom_server(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle custom server URL input."""
        errors: dict[str, str] = {}

        if user_input is not None:
            custom_url = user_input.get(CONF_CUSTOM_SERVER, "").strip()

            if not custom_url:
                errors[CONF_CUSTOM_SERVER] = "custom_server_required"
            else:
                # Create the entry with custom server using helper function
                data = _create_custom_server_data(
                    custom_url,
                    user_input.get(CONF_SKIP_CERT_VERIFY, False),
                    self._user_input,
                )

                # Generate unique ID for custom server
                unique_id = f"{DOMAIN}_{custom_url}"
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                # Extract domain from URL for title
                try:
                    parsed = urlparse(custom_url)
                    domain_name = parsed.netloc or custom_url
                except (ValueError, TypeError):
                    domain_name = custom_url

                return self.async_create_entry(
                    title=f"Pace - {domain_name}",
                    data=data,
                )

        return self.async_show_form(
            step_id="custom_server",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CUSTOM_SERVER,
                        default="https://",
                    ): str,
                    vol.Optional(
                        CONF_SKIP_CERT_VERIFY,
                        default=False,
                    ): bool,
                }
            ),
            errors=errors,
            description_placeholders={"example": "https://speedtest.example.com/"},
        )

    def _build_step_server_schema(self, config: dict[str, Any] | None = None) -> vol.Schema:
        """Build the server-selection-and-settings schema."""
        return _build_server_schema(self._servers, config)

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlow()


class OptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Pace."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._servers: list[dict[str, Any]] = []
        self._backend_type: str = DEFAULT_BACKEND_TYPE
        self._current_config: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the first step: backend choice only."""
        if user_input is None:
            current_config = dict(self.config_entry.data)
            current_config.update(self.config_entry.options)
            self._current_config = current_config
            return self.async_show_form(
                step_id="init",
                data_schema=_build_backend_schema(self.hass, current_config),
            )

        self._backend_type = user_input.get(CONF_BACKEND_TYPE, DEFAULT_BACKEND_TYPE)
        self._servers = await get_server_list(self.hass)
        return await self.async_step_server()

    async def async_step_server(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle server selection and the rest of the settings."""
        if user_input is None:
            config = {**self._current_config, CONF_BACKEND_TYPE: self._backend_type}
            if config.get(CONF_CUSTOM_SERVER):
                config["server_selection"] = "custom"
            elif config.get(CONF_SERVER_ID) is not None:
                config["server_selection"] = str(config[CONF_SERVER_ID])
            else:
                config["server_selection"] = "automatic"
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(config),
            )

        user_input[CONF_BACKEND_TYPE] = self._backend_type
        _LOGGER.debug("Options form received user_input: %s", user_input)
        server_selection = user_input.pop("server_selection", "automatic")

        if server_selection == "custom" and self._backend_type not in CUSTOM_SERVER_CAPABLE_BACKENDS:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={"base": "custom_server_not_supported"},
            )

        # A specific server ID only makes sense for the LibreSpeed backend
        # - see ConfigFlow.async_step_server for the full explanation.
        if server_selection not in ("automatic", "custom") and self._backend_type != BACKEND_LIBRESPEED:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={"server_selection": "server_id_requires_librespeed"},
            )

        scan_interval_minutes = _duration_dict_to_minutes(
            user_input.get(CONF_SCAN_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        )
        if not MIN_SCAN_INTERVAL <= scan_interval_minutes <= MAX_SCAN_INTERVAL:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={CONF_SCAN_INTERVAL: "invalid_scan_interval"},
            )

        try:
            _validate_ip_field(user_input.get(CONF_SOURCE_IP, ""))
        except vol.Invalid:
            return self.async_show_form(
                step_id="server",
                data_schema=self._build_step_server_schema(user_input),
                errors={CONF_SOURCE_IP: "invalid_source_ip"},
            )

        # Store settings temporarily
        self._user_input = user_input
        self._server_selection = server_selection

        # If custom server is selected, show custom URL form
        if server_selection == "custom":
            return await self.async_step_custom_server()

        # Parse the server selection using helper method
        server_id, custom_server = _parse_server_selection(server_selection)
        data = {
            CONF_SERVER_ID: server_id,
            CONF_CUSTOM_SERVER: custom_server,
        }

        data[CONF_AUTO_UPDATE] = user_input.get(CONF_AUTO_UPDATE, True)
        data[CONF_SCAN_INTERVAL] = scan_interval_minutes
        data[CONF_START_TIME] = (
            user_input.get(CONF_START_TIME) or ""
        ).strip() or None
        data[CONF_BACKEND_TYPE] = self._backend_type
        data[CONF_ISP_DOWNLOAD_SPEED] = user_input.get(
            CONF_ISP_DOWNLOAD_SPEED, DEFAULT_ISP_SPEED
        )
        data[CONF_ISP_UPLOAD_SPEED] = user_input.get(
            CONF_ISP_UPLOAD_SPEED, DEFAULT_ISP_SPEED
        )
        data[CONF_AUTO_REGISTER_CARDS] = user_input.get(
            CONF_AUTO_REGISTER_CARDS, DEFAULT_AUTO_REGISTER_CARDS
        )
        data[CONF_SOURCE_INTERFACE] = (
            user_input.get(CONF_SOURCE_INTERFACE) or ""
        ).strip() or None
        data[CONF_SOURCE_IP] = (
            user_input.get(CONF_SOURCE_IP) or ""
        ).strip() or None
        data[CONF_FALLBACK_TO_CLOSEST] = user_input.get(
            CONF_FALLBACK_TO_CLOSEST, DEFAULT_FALLBACK_TO_CLOSEST
        )
        # Preserve skip_cert_verify setting from existing config (check options first, then data)
        data[CONF_SKIP_CERT_VERIFY] = (
            self.config_entry.options.get(CONF_SKIP_CERT_VERIFY)
            if CONF_SKIP_CERT_VERIFY in self.config_entry.options
            else self.config_entry.data.get(CONF_SKIP_CERT_VERIFY, False)
        )

        # Store config but don't trigger immediate test
        _LOGGER.debug("Saving options data: %s", data)
        _LOGGER.info("Pace config updated - next test will use new settings")
        return self.async_create_entry(title="", data=data)

    async def async_step_custom_server(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle custom server URL input for options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            custom_url = user_input.get(CONF_CUSTOM_SERVER, "").strip()

            if not custom_url:
                errors[CONF_CUSTOM_SERVER] = "custom_server_required"
            else:
                # Create the entry with custom server using helper function
                data = _create_custom_server_data(
                    custom_url,
                    user_input.get(CONF_SKIP_CERT_VERIFY, False),
                    self._user_input,
                )

                _LOGGER.info(
                    "Pace config updated with custom server - next test will use new settings"
                )
                return self.async_create_entry(title="", data=data)

        # Show current custom server URL and skip cert verify setting if editing
        # Check options first, then data
        current_url = self.config_entry.options.get(
            CONF_CUSTOM_SERVER
        ) or self.config_entry.data.get(CONF_CUSTOM_SERVER, "https://")
        skip_cert = (
            self.config_entry.options.get(CONF_SKIP_CERT_VERIFY)
            if CONF_SKIP_CERT_VERIFY in self.config_entry.options
            else self.config_entry.data.get(CONF_SKIP_CERT_VERIFY, False)
        )

        return self.async_show_form(
            step_id="custom_server",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_CUSTOM_SERVER,
                        default=current_url,
                    ): str,
                    vol.Optional(
                        CONF_SKIP_CERT_VERIFY,
                        default=skip_cert,
                    ): bool,
                }
            ),
            errors=errors,
            description_placeholders={"example": "https://speedtest.example.com/"},
        )

    def _build_step_server_schema(self, config: dict[str, Any]) -> vol.Schema:
        """Build the server-selection-and-settings schema."""
        return _build_server_schema(self._servers, config)
