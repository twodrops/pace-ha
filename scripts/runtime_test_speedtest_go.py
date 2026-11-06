"""Standalone runtime test: actually run the speedtest-go backend (no mocks).

Not part of the pytest suite - this downloads the real binary (if missing)
and executes a real speed test against the network, printing timing info so
we can observe whether the process actually completes or hangs.

Usage: python scripts/runtime_test_speedtest_go.py
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from custom_components.pace.backends.speedtest_go_cli import (  # noqa: E402
    SpeedtestGoCLIBackend,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)

CONFIG_PATH = str(Path(__file__).resolve().parent.parent / ".runtime_test_data")
WATCHDOG_SECONDS = 180


async def main() -> None:
    """Run one real speed test and report timing/results."""
    backend = SpeedtestGoCLIBackend(CONFIG_PATH)

    _LOGGER.info("cli_path = %s", backend.cli_path)
    _LOGGER.info("is_cli_supported = %s", backend.is_cli_supported())

    exists = await backend.check_cli_exists()
    _LOGGER.info("check_cli_exists = %s", exists)

    if not exists:
        _LOGGER.info("Downloading speedtest-go binary...")
        start = time.monotonic()
        ok = await backend.ensure_cli_available()
        _LOGGER.info("Download finished in %.1fs, success=%s", time.monotonic() - start, ok)
        if not ok:
            _LOGGER.error("Could not download speedtest-go, aborting.")
            return

    _LOGGER.info("Starting run_speed_test() with a %ds watchdog...", WATCHDOG_SECONDS)
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            backend.run_speed_test(timeout=WATCHDOG_SECONDS),
            timeout=WATCHDOG_SECONDS + 10,
        )
        elapsed = time.monotonic() - start
        _LOGGER.info("run_speed_test() returned after %.1fs", elapsed)
        _LOGGER.info("Result: %s", result)
    except TimeoutError:
        elapsed = time.monotonic() - start
        _LOGGER.error(
            "WATCHDOG FIRED: run_speed_test() did not return within %.1fs "
            "(outer wait_for timeout) - this confirms it hangs.",
            elapsed,
        )
    except Exception:
        elapsed = time.monotonic() - start
        _LOGGER.exception("run_speed_test() raised after %.1fs", elapsed)

    # Check if the speedtest-go process is still alive/orphaned after our
    # code gave up - this is the actual "goes forever" symptom.
    proc = await asyncio.create_subprocess_shell(
        "pgrep -fa speedtest-go || true",
        stdout=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    leftover = stdout.decode().strip()
    if leftover:
        _LOGGER.warning("Leftover speedtest-go process(es) still running:\n%s", leftover)
    else:
        _LOGGER.info("No leftover speedtest-go processes found.")


if __name__ == "__main__":
    asyncio.run(main())
