"""Repair flows for Pace integration."""

from __future__ import annotations

import asyncio
import logging

import aiohttp
import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .backends.librespeed_cli import LibreSpeedCLIBackend
from .backends.ookla_cli import OoklaCLIBackend
from .backends.speedtest_go_cli import SpeedtestGoCLIBackend
from .const import (
    BACKEND_OOKLA,
    BACKEND_SPEEDTEST_GO,
    CIRCUIT_BREAKER_OPEN_THRESHOLD,
    CIRCUIT_BREAKER_WARNING_THRESHOLD,
    CONF_BACKEND_TYPE,
    DEFAULT_BACKEND_TYPE,
    DOMAIN,
    LOGGER_NAME,
)

_LOGGER = logging.getLogger(LOGGER_NAME)

def _backend_class_for_first_entry(hass: HomeAssistant):
    """Pick the CLI backend class matching the first configured entry.

    Repair issues like "cli_download_failed" are domain-scoped (not tied to
    one config entry), so with multiple instances this just retries using
    whichever backend the first found entry is configured for.

    Looks up classes by bare module-global name (not a dict literal built at
    import time) so tests can patch e.g.
    "custom_components.pace.repairs.LibreSpeedCLIBackend" and have it
    take effect here.
    """
    entries = hass.config_entries.async_entries(DOMAIN)
    backend_type = DEFAULT_BACKEND_TYPE
    if entries:
        entry = entries[0]
        backend_type = entry.options.get(
            CONF_BACKEND_TYPE, entry.data.get(CONF_BACKEND_TYPE, DEFAULT_BACKEND_TYPE)
        )
    if backend_type == BACKEND_OOKLA:
        return OoklaCLIBackend
    if backend_type == BACKEND_SPEEDTEST_GO:
        return SpeedtestGoCLIBackend
    return LibreSpeedCLIBackend


class CLIDownloadRepairFlow(RepairsFlow):
    """Handler for CLI download failure repair flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of CLI download repair."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step to retry CLI download."""
        if user_input is not None:
            # Attempt to re-download CLI
            _LOGGER.info("User initiated CLI download retry via repair flow")
            backend_cls = _backend_class_for_first_entry(self.hass)
            cli = backend_cls(self.hass.config.path())

            try:
                if await cli.ensure_cli_available(force_download=True):
                    _LOGGER.info("CLI download successful via repair flow")
                    # Delete the repair issue since it's fixed
                    ir.async_delete_issue(self.hass, DOMAIN, "cli_download_failed")
                    return self.async_create_entry(
                        title="CLI Download Successful", data={}
                    )
                _LOGGER.error("CLI download failed again via repair flow")
                return self.async_abort(reason="cli_download_failed")
            except (OSError, aiohttp.ClientError, asyncio.TimeoutError) as e:
                _LOGGER.error("CLI download repair failed with exception: %s", e)
                return self.async_abort(reason="cli_download_error")

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "alternative": "You can also switch to a different backend in integration options"
            },
        )


class CustomServerRepairFlow(RepairsFlow):
    """Handler for custom server unreachable repair flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of custom server repair."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step to guide user to options."""
        if user_input is not None:
            _LOGGER.info("User acknowledged custom server issue via repair flow")
            # We can't automatically fix server issues, just guide user to options
            return self.async_create_entry(title="Server Configuration", data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "options_path": "Settings → Devices & Services → Pace → Configure"
            },
        )


class RepeatedFailuresRepairFlow(RepairsFlow):
    """Handler for repeated test failures repair flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of repeated failures repair."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step to reset failure counter and suggest fixes."""
        if user_input is not None:
            _LOGGER.info("User initiated failure recovery via repair flow")

            # Reset the failure counter in the coordinator
            # This allows the integration to try again
            from . import PaceRuntimeData

            # Find the config entry with this issue
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if hasattr(entry, "runtime_data") and isinstance(
                    entry.runtime_data, PaceRuntimeData
                ):
                    coordinator = entry.runtime_data.coordinator
                    if (
                        coordinator.consecutive_failures
                        >= CIRCUIT_BREAKER_WARNING_THRESHOLD
                    ):
                        _LOGGER.info(
                            "Resetting failure counter from %d to 0",
                            coordinator.consecutive_failures,
                        )
                        coordinator.consecutive_failures = 0

                        # Delete the repair issue
                        ir.async_delete_issue(
                            self.hass, DOMAIN, "repeated_test_failures"
                        )
                        ir.async_delete_issue(self.hass, DOMAIN, "circuit_breaker_open")

                        return self.async_create_entry(
                            title="Failure Counter Reset", data={}
                        )

            return self.async_create_entry(title="Recovery Initiated", data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "action": "Reset failure counter and allow retries",
                "backend_switch": "Consider switching to a different backend in integration options",
                "options_path": "Settings → Devices & Services → Pace → Configure",
            },
        )


class CircuitBreakerRepairFlow(RepairsFlow):
    """Handler for circuit breaker open repair flow."""

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the first step of circuit breaker repair."""
        return await self.async_step_confirm()

    async def async_step_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Handle the confirm step to reset circuit breaker."""
        if user_input is not None:
            _LOGGER.info("User initiated circuit breaker reset via repair flow")

            # Reset the circuit breaker
            from . import PaceRuntimeData

            # Find and reset all coordinators with open circuit
            reset_count = 0
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                if hasattr(entry, "runtime_data") and isinstance(
                    entry.runtime_data, PaceRuntimeData
                ):
                    coordinator = entry.runtime_data.coordinator
                    if (
                        coordinator.consecutive_failures
                        >= CIRCUIT_BREAKER_OPEN_THRESHOLD
                    ):
                        _LOGGER.info(
                            "Resetting circuit breaker for %s (failures: %d)",
                            coordinator.entry_title,
                            coordinator.consecutive_failures,
                        )
                        coordinator.consecutive_failures = 0
                        reset_count += 1

            if reset_count > 0:
                # Delete the repair issue
                ir.async_delete_issue(self.hass, DOMAIN, "circuit_breaker_open")
                ir.async_delete_issue(self.hass, DOMAIN, "repeated_test_failures")

                return self.async_create_entry(
                    title=f"Circuit Breaker Reset ({reset_count} instance{'s' if reset_count > 1 else ''})",
                    data={},
                )

            return self.async_create_entry(title="No Circuit Breakers Found", data={})

        return self.async_show_form(
            step_id="confirm",
            data_schema=vol.Schema({}),
            description_placeholders={
                "action": "Reset the circuit breaker to allow speed tests to resume",
                "note": "The integration will attempt tests again on the next scheduled interval",
            },
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, str | int | float | None] | None,
) -> RepairsFlow:
    """Create repair flow based on issue ID."""
    _LOGGER.debug("Creating repair flow for issue: %s", issue_id)

    if issue_id == "cli_download_failed":
        return CLIDownloadRepairFlow()
    if issue_id == "custom_server_unreachable":
        return CustomServerRepairFlow()
    if issue_id == "repeated_test_failures":
        return RepeatedFailuresRepairFlow()
    if issue_id == "circuit_breaker_open":
        return CircuitBreakerRepairFlow()

    # Fallback to simple confirmation flow
    return ConfirmRepairFlow()
