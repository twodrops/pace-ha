"""Tests for Pace config flow."""

from __future__ import annotations

from collections.abc import Generator
from copy import deepcopy
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.pace.config_flow import (
    _build_backend_schema,
    _build_server_schema,
    _duration_dict_to_minutes,
    _minutes_to_duration_dict,
    _parse_server_selection,
    _validate_ip_field,
    get_server_list,
)
from custom_components.pace.const import (
    CONF_AUTO_UPDATE,
    CONF_BACKEND_TYPE,
    CONF_CONNECTIVITY_CHECK_INTERVAL,
    CONF_CUSTOM_SERVER,
    CONF_FALLBACK_TO_CLOSEST,
    CONF_SCAN_INTERVAL,
    CONF_SERVER_ID,
    CONF_SKIP_CERT_VERIFY,
    CONF_SOURCE_INTERFACE,
    CONF_SOURCE_IP,
    CONF_START_TIME,
    CONF_TEST_TIMEOUT,
    DEFAULT_CONNECTIVITY_CHECK_INTERVAL,
    DEFAULT_TEST_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_CONNECTIVITY_CHECK_INTERVAL,
    MIN_CONNECTIVITY_CHECK_INTERVAL,
)

from .conftest import MOCK_SERVER_LIST


@pytest.fixture(autouse=True)
def mock_setup_entry() -> Generator[None]:
    """Prevent actual integration setup during config flow tests."""
    with (
        patch(
            "custom_components.pace.async_setup_entry",
            return_value=True,
        ),
        patch(
            "custom_components.pace.async_unload_entry",
            return_value=True,
        ),
    ):
        yield


@pytest.fixture
def mock_server_list() -> Generator[None]:
    """Mock get_server_list to return test servers."""
    with patch(
        "custom_components.pace.config_flow.get_server_list",
        return_value=deepcopy(MOCK_SERVER_LIST),
    ):
        yield


@pytest.fixture
def mock_cli_supported() -> Generator[None]:
    """Mock every backend's CLI as supported on this platform."""
    with (
        patch("custom_components.pace.config_flow.LibreSpeedCLIBackend") as mock_ls,
        patch("custom_components.pace.config_flow.OoklaCLIBackend") as mock_ookla,
        patch("custom_components.pace.config_flow.SpeedtestGoCLIBackend") as mock_stg,
    ):
        for mock_cls in (mock_ls, mock_ookla, mock_stg):
            mock_cls.return_value.is_cli_supported.return_value = True
        yield


def _server_payload(server_selection: str, **extra: object) -> dict:
    """Build a typical step-2 ("server") form submission payload."""
    payload = {
        "server_selection": server_selection,
        CONF_AUTO_UPDATE: True,
        CONF_SCAN_INTERVAL: _minutes_to_duration_dict(DEFAULT_UPDATE_INTERVAL),
        CONF_TEST_TIMEOUT: DEFAULT_TEST_TIMEOUT,
    }
    payload.update(extra)
    return payload


# ---- User flow ----


async def test_user_flow_show_form(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test initial form is shown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_flow_backend_step_leads_to_server_step(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test submitting the backend choice moves to the server step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "server"


async def test_user_flow_automatic_server(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test selecting automatic server creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("automatic")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Pace (Automatic)"
    assert result["data"][CONF_SERVER_ID] is None
    assert result["data"][CONF_CUSTOM_SERVER] is None


async def test_user_flow_specific_server(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test selecting a specific server."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("1")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SERVER_ID] == 1
    assert "Server One" in result["title"]


async def test_user_flow_specific_server_id_unavailable_for_ookla(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test the server step's dropdown genuinely excludes LibreSpeed server
    IDs for Ookla - submitting one is rejected at the schema level, proving
    the list is correctly filtered rather than just cosmetically hidden."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "ookla"}
    )
    with pytest.raises(Exception):
        await hass.config_entries.flow.async_configure(
            result["flow_id"], _server_payload("1")
        )


async def test_user_flow_automatic_server_accepted_for_ookla(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test 'Automatic' is always accepted regardless of backend."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "ookla"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("automatic")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SERVER_ID] is None


async def test_user_flow_custom_server_redirect(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test selecting custom server redirects to custom_server step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("custom")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom_server"


async def test_user_flow_abort_already_configured(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test abort when already configured."""
    # Set up first entry
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("automatic")
    )

    # Try to set up duplicate
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("automatic")
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# ---- Custom server step ----


async def test_custom_server_show_form(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test custom server form is shown."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("custom")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom_server"


async def test_custom_server_success(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test custom server creates entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("custom")
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_CUSTOM_SERVER: "https://speedtest.example.com/",
            CONF_SKIP_CERT_VERIFY: False,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CUSTOM_SERVER] == "https://speedtest.example.com/"
    assert "speedtest.example.com" in result["title"]


async def test_custom_server_empty_url(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test empty custom URL shows error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], _server_payload("custom")
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_CUSTOM_SERVER: "", CONF_SKIP_CERT_VERIFY: False},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_CUSTOM_SERVER] == "custom_server_required"


# ---- Helper functions ----


def test_parse_server_selection_automatic() -> None:
    """Test parsing 'automatic'."""
    assert _parse_server_selection("automatic") == (None, None)


def test_parse_server_selection_custom() -> None:
    """Test parsing 'custom'."""
    assert _parse_server_selection("custom") == (None, None)


def test_parse_server_selection_valid_id() -> None:
    """Test parsing valid server ID."""
    assert _parse_server_selection("42") == (42, None)


def test_parse_server_selection_invalid_string() -> None:
    """Test parsing invalid string returns None."""
    assert _parse_server_selection("abc") == (None, None)


def test_parse_server_selection_out_of_range() -> None:
    """Test parsing out-of-range ID returns None."""
    assert _parse_server_selection("99999") == (None, None)


def test_parse_server_selection_negative() -> None:
    """Test parsing negative ID returns None."""
    assert _parse_server_selection("-1") == (None, None)


async def test_get_server_list_success(hass: HomeAssistant) -> None:
    """Test get_server_list returns servers."""
    with patch(
        "custom_components.pace.config_flow.fetch_server_list",
        AsyncMock(return_value=deepcopy(MOCK_SERVER_LIST)),
    ):
        result = await get_server_list(hass)
    assert len(result) == 2


async def test_get_server_list_error(hass: HomeAssistant) -> None:
    """Test get_server_list returns empty on error."""
    with patch(
        "custom_components.pace.config_flow.fetch_server_list",
        AsyncMock(return_value=[]),
    ):
        result = await get_server_list(hass)
    assert result == []


# ---- Options flow ----


async def test_options_flow_show_form(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test options flow shows the backend-choice form first."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: None,
            CONF_CUSTOM_SERVER: None,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"


async def test_options_flow_backend_step_leads_to_server_step(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test submitting the backend choice moves to the server step."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: None,
            CONF_CUSTOM_SERVER: None,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts_step",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "server"


async def test_options_flow_automatic(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test options flow with automatic server."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: None,
            CONF_CUSTOM_SERVER: None,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts2",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _server_payload("automatic")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SERVER_ID] is None


async def test_options_flow_custom_server_redirect(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test options flow redirects to custom server step."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: None,
            CONF_CUSTOM_SERVER: None,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts3",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _server_payload("custom")
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "custom_server"


async def test_options_flow_custom_server_success(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test options flow custom server step creates entry."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: None,
            CONF_CUSTOM_SERVER: None,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts4",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _server_payload("custom")
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_CUSTOM_SERVER: "https://custom.example.com/",
            CONF_SKIP_CERT_VERIFY: True,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_CUSTOM_SERVER] == "https://custom.example.com/"
    assert result["data"][CONF_SKIP_CERT_VERIFY] is True


async def test_options_flow_custom_server_empty(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test options flow custom server empty URL shows error."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: None,
            CONF_CUSTOM_SERVER: None,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts5",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _server_payload("custom")
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_CUSTOM_SERVER: "", CONF_SKIP_CERT_VERIFY: False},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_CUSTOM_SERVER] == "custom_server_required"


async def test_options_flow_preserves_skip_cert(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test options flow preserves skip_cert_verify from existing config."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: None,
            CONF_CUSTOM_SERVER: "https://old.example.com/",
            CONF_SKIP_CERT_VERIFY: True,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts6",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], _server_payload("automatic")
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SKIP_CERT_VERIFY] is True


async def test_options_flow_server_step_prefills_existing_server_selection(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test the server step's default reflects the entry's current server_id."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry as MCE

    entry = MCE(
        domain=DOMAIN,
        data=deepcopy({
            CONF_SERVER_ID: 1,
            CONF_CUSTOM_SERVER: None,
            CONF_AUTO_UPDATE: True,
            CONF_SCAN_INTERVAL: DEFAULT_UPDATE_INTERVAL,
            CONF_BACKEND_TYPE: "librespeed",
        }),
        unique_id="pace_opts7",
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "server"
    for key in result["data_schema"].schema:
        if str(key) == "server_selection":
            assert key.default() == "1"
            return
    raise AssertionError("server_selection key not found in schema")


# ---- Duration <-> minutes conversion helpers ----


def test_minutes_to_duration_dict_basic() -> None:
    """Test converting plain minutes to a duration dict."""
    assert _minutes_to_duration_dict(90) == {"hours": 1, "minutes": 30, "seconds": 0}
    assert _minutes_to_duration_dict(60) == {"hours": 1, "minutes": 0, "seconds": 0}


def test_minutes_to_duration_dict_passthrough() -> None:
    """Test it's idempotent when already given a dict."""
    existing = {"hours": 2, "minutes": 0, "seconds": 0}
    assert _minutes_to_duration_dict(existing) is existing


def test_duration_dict_to_minutes_basic() -> None:
    """Test converting a duration dict back to minutes."""
    assert _duration_dict_to_minutes({"hours": 1, "minutes": 30, "seconds": 0}) == 90
    assert _duration_dict_to_minutes({"hours": 0, "minutes": 45, "seconds": 0}) == 45


def test_duration_dict_to_minutes_plain_int_backcompat() -> None:
    """Test it accepts a plain int for backwards compatibility."""
    assert _duration_dict_to_minutes(60) == 60


# ---- Source IP validation ----


def test_validate_ip_field_accepts_blank() -> None:
    """Test an empty source IP field is allowed (feature disabled)."""
    assert _validate_ip_field("") == ""
    assert _validate_ip_field("   ") == ""


def test_validate_ip_field_accepts_valid_ip() -> None:
    """Test a valid IPv4/IPv6 address passes validation."""
    assert _validate_ip_field("10.20.0.101") == "10.20.0.101"
    assert _validate_ip_field("::1") == "::1"


def test_validate_ip_field_rejects_invalid_ip() -> None:
    """Test an invalid IP string raises vol.Invalid."""
    import voluptuous as vol

    with pytest.raises(vol.Invalid):
        _validate_ip_field("not-an-ip")


# ---- Backend-aware server dropdown ----


def _server_selection_options(backend_type: str) -> list[str]:
    """Extract the "server_selection" dropdown's option values from the built schema."""
    schema = _build_server_schema(
        deepcopy(MOCK_SERVER_LIST), {CONF_BACKEND_TYPE: backend_type}
    )
    for key, validator in schema.schema.items():
        if str(key) == "server_selection":
            return [opt["value"] for opt in validator.config["options"]]
    raise AssertionError("server_selection key not found in schema")


def test_server_dropdown_shows_librespeed_servers_for_librespeed() -> None:
    """Test the numeric server list and Custom option are shown for LibreSpeed."""
    options = _server_selection_options("librespeed")
    assert "automatic" in options
    assert "1" in options
    assert "custom" in options


def test_server_dropdown_hides_server_list_for_ookla() -> None:
    """Test the LibreSpeed-only numeric server list and Custom are hidden for Ookla."""
    options = _server_selection_options("ookla")
    assert options == ["automatic"]


def test_server_dropdown_hides_server_list_but_shows_custom_for_speedtest_go() -> None:
    """Test speedtest-go hides the LibreSpeed list but keeps Custom (it supports one)."""
    options = _server_selection_options("speedtest_go")
    assert options == ["automatic", "custom"]


def test_backend_schema_offers_supported_backends(
    hass: HomeAssistant, mock_cli_supported
) -> None:
    """Test the backend-only schema offers all CLI-supported backends."""
    schema = _build_backend_schema(hass)
    for key, validator in schema.schema.items():
        if str(key) == CONF_BACKEND_TYPE:
            values = [opt["value"] for opt in validator.config["options"]]
            assert "librespeed" in values
            assert "ookla" in values
            assert "speedtest_go" in values
            return
    raise AssertionError("backend_type key not found in schema")


# ---- Connectivity check interval ----


def test_connectivity_check_interval_default_and_bounds() -> None:
    """Test the connectivity_check_interval field has the right default and min/max."""
    schema = _build_server_schema(deepcopy(MOCK_SERVER_LIST), {})
    for key, validator in schema.schema.items():
        if str(key) == CONF_CONNECTIVITY_CHECK_INTERVAL:
            assert key.default() == DEFAULT_CONNECTIVITY_CHECK_INTERVAL
            assert validator.config["min"] == MIN_CONNECTIVITY_CHECK_INTERVAL
            assert validator.config["max"] == MAX_CONNECTIVITY_CHECK_INTERVAL
            return
    raise AssertionError("connectivity_check_interval key not found in schema")


def test_connectivity_check_interval_uses_existing_value() -> None:
    """Test an existing configured value is used as the schema default, not the hardcoded one."""
    schema = _build_server_schema(
        deepcopy(MOCK_SERVER_LIST), {CONF_CONNECTIVITY_CHECK_INTERVAL: 120}
    )
    for key, _validator in schema.schema.items():
        if str(key) == CONF_CONNECTIVITY_CHECK_INTERVAL:
            assert key.default() == 120
            return
    raise AssertionError("connectivity_check_interval key not found in schema")


# ---- Frontend schema serialization (regression) ----
#
# pytest-homeassistant-custom-component's async_configure() operates on the
# live vol.Schema object directly - it never exercises the HTTP/websocket
# layer that converts a schema to JSON for the frontend. A schema that uses
# vol.Any(...)/vol.All(..., <plain function>) can pass every flow test here
# while still crashing voluptuous_serialize.convert() in a real HA instance,
# which the user sees as "Unknown error occurred" with no useful form.


def _assert_schema_serializes(schema) -> None:
    """Fail loudly if HA's frontend couldn't render this schema at all."""
    from homeassistant.helpers import config_validation as cv
    import voluptuous_serialize

    voluptuous_serialize.convert(schema, custom_serializer=cv.custom_serializer)


def test_backend_schema_serializes_for_frontend(
    hass: HomeAssistant, mock_cli_supported
) -> None:
    """Test the backend-only schema can be converted for the frontend."""
    _assert_schema_serializes(_build_backend_schema(hass))


def test_server_schema_serializes_for_frontend_with_no_existing_values() -> None:
    """Test the server schema serializes with no prior config (new entry)."""
    _assert_schema_serializes(
        _build_server_schema(
            deepcopy(MOCK_SERVER_LIST), {CONF_BACKEND_TYPE: "librespeed"}
        )
    )


def test_server_schema_serializes_for_frontend_with_existing_values() -> None:
    """Test the server schema serializes once start_time/source_ip are set
    (options flow editing an existing entry) - this is exactly the scenario
    that used to crash with vol.Any()/vol.All(..., custom_function)."""
    _assert_schema_serializes(
        _build_server_schema(
            deepcopy(MOCK_SERVER_LIST),
            {
                CONF_BACKEND_TYPE: "librespeed",
                CONF_START_TIME: "14:00:00",
                CONF_SOURCE_IP: "10.20.0.101",
                CONF_SOURCE_INTERFACE: "eth0",
            },
        )
    )


def test_server_schema_start_time_field_order() -> None:
    """Test Start Time appears right after Test Interval, not at the end."""
    schema = _build_server_schema(
        deepcopy(MOCK_SERVER_LIST), {CONF_BACKEND_TYPE: "librespeed"}
    )
    keys = [str(key) for key in schema.schema]
    assert keys.index(CONF_START_TIME) == keys.index(CONF_SCAN_INTERVAL) + 1


# ---- New fields end-to-end through the user flow ----


async def test_user_flow_with_new_fields(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test source_interface/source_ip/start_time/fallback_to_closest persist."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _server_payload(
            "automatic",
            **{
                CONF_SOURCE_INTERFACE: "eth0",
                CONF_SOURCE_IP: "10.20.0.101",
                CONF_START_TIME: "00:00:00",
                CONF_FALLBACK_TO_CLOSEST: True,
            },
        ),
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SOURCE_INTERFACE] == "eth0"
    assert result["data"][CONF_SOURCE_IP] == "10.20.0.101"
    assert result["data"][CONF_START_TIME] == "00:00:00"
    assert result["data"][CONF_FALLBACK_TO_CLOSEST] is True


async def test_user_flow_invalid_source_ip_rejected(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test an invalid source IP is rejected with a form error."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _server_payload("automatic", **{CONF_SOURCE_IP: "not-an-ip"}),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_SOURCE_IP] == "invalid_source_ip"


async def test_user_flow_scan_interval_out_of_bounds_shows_error(
    hass: HomeAssistant, mock_server_list, mock_cli_supported
) -> None:
    """Test a scan interval outside 30min-24h bounds shows an error, not a crash."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_BACKEND_TYPE: "librespeed"}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        _server_payload(
            "automatic", **{CONF_SCAN_INTERVAL: {"hours": 0, "minutes": 5, "seconds": 0}}
        ),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"][CONF_SCAN_INTERVAL] == "invalid_scan_interval"
