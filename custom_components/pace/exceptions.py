"""Custom exceptions for the Pace integration."""

from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError


class PaceError(HomeAssistantError):
    """Base exception for the Pace integration."""


class ServerNotFoundError(PaceError):
    """Raised when a requested server is not found."""


class NetworkError(PaceError):
    """Raised when network operations fail."""


class SpeedTestError(PaceError):
    """Raised when a speed test fails."""


class SpeedTestTimeoutError(SpeedTestError):
    """Raised when speed test times out."""


class CLIError(PaceError):
    """Base exception for CLI backend errors."""


class CLINotFoundError(CLIError):
    """Raised when CLI binary is not found."""


class CLIExecutionError(CLIError):
    """Raised when CLI execution fails."""


class CLIOutputError(CLIError):
    """Raised when CLI output cannot be parsed."""
