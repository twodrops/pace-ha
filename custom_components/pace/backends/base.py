"""Shared interface implemented by every Pace CLI backend."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SpeedTestBackend(Protocol):
    """Protocol implemented by every CLI backend (LibreSpeed/Ookla/speedtest-go).

    Each backend wraps a specific external CLI binary but exposes this same
    interface so the coordinator never needs backend-specific branching.
    All backends must return a result dict with this exact shape from
    run_speed_test():

        {
            "download": float,            # Mbps
            "upload": float,               # Mbps
            "ping": float,                 # ms
            "jitter": float,                # ms
            "server": {
                "name": str,
                "location": str,
                "sponsor": str,
            },
            "timestamp": datetime,
            "bytes_sent": int,
            "bytes_received": int,
        }
    """

    async def check_cli_exists(self) -> bool:
        """Return True if the backend's CLI binary is already installed."""
        ...

    async def ensure_cli_available(self, force_download: bool = False) -> bool:
        """Download/install the CLI binary if needed. Return True on success."""
        ...

    def is_cli_supported(self) -> bool:
        """Return True if this backend's CLI has a build for this platform."""
        ...

    async def run_speed_test(
        self,
        server_id: int | None = None,
        custom_server: str | None = None,
        skip_cert_verify: bool = False,
        timeout: int = 120,
        source_interface: str | None = None,
        source_ip: str | None = None,
    ) -> dict[str, Any]:
        """Run one speed test and return the unified result dict.

        source_interface/source_ip bind the test to a specific network
        interface or source IP on the machine running Home Assistant (not a
        remote device). At most one is normally set; if both are given, a
        backend may prefer one over the other.
        """
        ...
