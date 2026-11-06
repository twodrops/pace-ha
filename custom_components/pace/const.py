"""Constants for the Pace integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pace"
LOGGER_NAME: Final = "custom_components.pace"

DEFAULT_UPDATE_INTERVAL = 60

CONF_SERVER_ID = "server_id"
CONF_CUSTOM_SERVER = "custom_server"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_AUTO_UPDATE = "auto_update"
CONF_SKIP_CERT_VERIFY = "skip_cert_verify"
CONF_BACKEND_TYPE = "backend_type"
CONF_TEST_TIMEOUT = "test_timeout"
CONF_ISP_DOWNLOAD_SPEED = "isp_download_speed"
CONF_ISP_UPLOAD_SPEED = "isp_upload_speed"
CONF_AUTO_REGISTER_CARDS = "auto_register_cards"
CONF_SOURCE_INTERFACE = "source_interface"
CONF_SOURCE_IP = "source_ip"
CONF_START_TIME = "start_time"
CONF_FALLBACK_TO_CLOSEST = "fallback_to_closest"

DEFAULT_AUTO_REGISTER_CARDS = False
DEFAULT_FALLBACK_TO_CLOSEST = False

# Backend choices. Each is a standalone CLI binary wrapper implementing the
# same run_speed_test() interface - see backends/base.py.
BACKEND_LIBRESPEED = "librespeed"
BACKEND_OOKLA = "ookla"
BACKEND_SPEEDTEST_GO = "speedtest_go"
BACKENDS: Final = (BACKEND_LIBRESPEED, BACKEND_OOKLA, BACKEND_SPEEDTEST_GO)
DEFAULT_BACKEND_TYPE = BACKEND_LIBRESPEED

# Backends that support testing against a self-hosted/custom server instead
# of the backend's public server network. Ookla has no such concept.
CUSTOM_SERVER_CAPABLE_BACKENDS: Final = (BACKEND_LIBRESPEED, BACKEND_SPEEDTEST_GO)

# Device registry manufacturer/model/URL per backend - entities stay
# identical regardless of backend, but the device card should reflect which
# upstream CLI project a given config entry actually runs.
BACKEND_DEVICE_INFO: Final = {
    BACKEND_LIBRESPEED: {
        "manufacturer": "LibreSpeed",
        "model": "LibreSpeed CLI",
        "configuration_url": "https://librespeed.org/",
    },
    BACKEND_OOKLA: {
        "manufacturer": "Ookla",
        "model": "Speedtest CLI",
        "configuration_url": "https://www.speedtest.net/apps/cli",
    },
    BACKEND_SPEEDTEST_GO: {
        "manufacturer": "speedtest-go",
        "model": "speedtest-go CLI",
        "configuration_url": "https://github.com/showwin/speedtest-go",
    },
}

SERVICE_REGISTER_CARD_RESOURCES = "register_card_resources"
SERVICE_REMOVE_CARD_RESOURCES = "remove_card_resources"

MIN_SCAN_INTERVAL = 30
MAX_SCAN_INTERVAL = 1440
DEFAULT_TEST_TIMEOUT = 240  # 4 minutes
MIN_TEST_TIMEOUT = 60  # 1 minute
MAX_TEST_TIMEOUT = 600  # 10 minutes

# ISP rated speed, used to calculate plan compliance percentage
# A value of 0 means compliance sensors are disabled (not configured)
MIN_ISP_SPEED = 0
MAX_ISP_SPEED = 100000  # Mbit/s
DEFAULT_ISP_SPEED = 0

ATTR_DOWNLOAD = "download"
ATTR_UPLOAD = "upload"
ATTR_PING = "ping"
ATTR_JITTER = "jitter"
ATTR_SERVER_NAME = "server_name"
ATTR_SERVER_LOCATION = "server_location"
ATTR_SERVER_SPONSOR = "server_sponsor"
ATTR_TIMESTAMP = "timestamp"
ATTR_BYTES_SENT = "bytes_sent"
ATTR_BYTES_RECEIVED = "bytes_received"
ATTR_LIFETIME_DOWNLOAD = "lifetime_download"
ATTR_LIFETIME_UPLOAD = "lifetime_upload"
ATTR_DOWNLOAD_COMPLIANCE = "download_compliance"
ATTR_UPLOAD_COMPLIANCE = "upload_compliance"

# Circuit breaker thresholds
CIRCUIT_BREAKER_WARNING_THRESHOLD = (
    5  # Show warning repair issue after this many failures
)
CIRCUIT_BREAKER_OPEN_THRESHOLD = (
    10  # Circuit breaker opens after this many consecutive failures
)

# CLI download timeouts (shared by all 3 CLI backends' binary download step)
CLI_DOWNLOAD_TIMEOUT_TOTAL = 300  # 5 minutes total timeout for CLI download
CLI_DOWNLOAD_TIMEOUT_CONNECT = 30  # 30 seconds to establish connection
CLI_DOWNLOAD_TIMEOUT_READ = 60  # 60 seconds for socket reads

# Timeout waiting for another instance's speed test to finish (5 minutes)
GLOBAL_TEST_LOCK_TIMEOUT = 300

# Startup delays
NETWORK_STABILIZATION_DELAY = 2  # Seconds to wait for network to stabilize on startup
FIRST_TEST_DELAY = 60  # Seconds to wait before first automatic speed test

# Retry configuration
CLI_DOWNLOAD_MAX_RETRIES = 3  # Maximum retries for CLI binary download
CLI_DOWNLOAD_RETRY_DELAY = 5  # Base delay between CLI download retries in seconds
MAX_RETRIES = 3  # Maximum number of retry attempts for failed tests
RETRY_DELAY_BASE = 5  # Base delay in seconds for exponential backoff (5, 10, 20...)

# Server validation
MIN_SERVER_ID = 0
MAX_SERVER_ID = 10000

# Custom server error cooldown
CUSTOM_SERVER_ERROR_COOLDOWN = 21600  # 6 hours in seconds

# HTTP status codes
HTTP_OK = 200  # Success status code

# Process return codes
PROCESS_SUCCESS = 0  # Successful process execution

# Default timeout for speed tests
DEFAULT_SPEED_TEST_TIMEOUT = 120  # 2 minutes

# Data limits
MAX_LIFETIME_GB = 1_000_000  # Maximum lifetime data in GB (1 petabyte)

# Network validation
MAX_HOSTNAME_LENGTH = 253  # Maximum length for a hostname

# --- Ookla CLI backend ---
OOKLA_CLI_VERSION = "1.2.0"
OOKLA_CLI_DOWNLOAD_BASE = "https://install.speedtest.net/app/cli"
OOKLA_ACCEPT_LICENSE_FLAGS: Final = ("--accept-license", "--accept-gdpr")

# --- speedtest-go CLI backend ---
SPEEDTEST_GO_GITHUB_REPO = "showwin/speedtest-go"

# --- Lightweight internet-connectivity / public-IP check ---
# Independent of the (much heavier, much less frequent) speed test cycle, so
# "Internet Connected"/"Public IP Address" stay fresh even when auto_update
# is off or scan_interval is long. Uses our own small HTTP probe rather than
# a given CLI backend's own client-IP reporting, which proved unreliable for
# at least one backend (confirmed live: librespeed-cli's --json "client.ip"
# is always empty even though its verbose text output shows the real IP).
CONF_CONNECTIVITY_CHECK_INTERVAL = "connectivity_check_interval"
DEFAULT_CONNECTIVITY_CHECK_INTERVAL = 30  # seconds between checks
MIN_CONNECTIVITY_CHECK_INTERVAL = 10  # seconds
MAX_CONNECTIVITY_CHECK_INTERVAL = 300  # 5 minutes
CONNECTIVITY_CHECK_URL = "https://api.ipify.org?format=json"
CONNECTIVITY_CHECK_TIMEOUT = 10  # seconds

