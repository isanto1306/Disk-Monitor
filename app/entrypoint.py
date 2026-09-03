import asyncio
import json

from datetime import datetime, timezone
from pathlib import Path

import main


# Runtime backend version for this image. The main module remains the core
# implementation; this entrypoint adds installation-specific startup policy.
main.app.version = "0.22.15"
app = main.app


FIRST_START_SMART_CHECK_FILE = Path(
    "/app/cache/first_start_smart_check.json"
)

# Determine whether this is a genuinely fresh persistent AppData/cache before
# main's startup tasks can create any cache files. Existing installations and
# normal container restarts therefore keep the regular no-wake startup policy.
CACHE_DIR = FIRST_START_SMART_CHECK_FILE.parent
try:
    CACHE_WAS_EMPTY_AT_PROCESS_START = (
        not CACHE_DIR.exists()
        or not any(CACHE_DIR.iterdir())
    )
except Exception:
    CACHE_WAS_EMPTY_AT_PROCESS_START = False

_original_startup_smart_check = main.run_startup_smart_check


async def run_startup_smart_check_with_first_install():
    """Run one forced SMART refresh on a fresh installation.

    The first installation check intentionally allows SMART reads to wake
    sleeping HDDs so Disk Monitor starts with an initial SMART data set for all
    detected physical drives. After that one-time check, ordinary application
    restarts use the original no-wake startup behavior from main.py.
    """

    first_install = (
        CACHE_WAS_EMPTY_AT_PROCESS_START
        and not FIRST_START_SMART_CHECK_FILE.exists()
    )

    if not first_install:
        await _original_startup_smart_check()
        return

    # Give /dev and sysfs a short moment to settle after container startup.
    await asyncio.sleep(3)

    attempted = []
    succeeded = []
    failed = []

    for device, _device_path in main.get_devices():
        attempted.append(device)

        try:
            await asyncio.to_thread(
                main.read_smart_now,
                device,
                "first-install"
            )
            succeeded.append(device)
        except Exception as exc:
            failed.append(
                {
                    "device": device,
                    "error": type(exc).__name__
                }
            )

        await asyncio.sleep(0.25)

    # If no devices were visible yet, do not mark the first-install check as
    # finished. A later process start can try again.
    if not attempted:
        return

    try:
        FIRST_START_SMART_CHECK_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = FIRST_START_SMART_CHECK_FILE.with_suffix(
            ".tmp"
        )
        temp_file.write_text(
            json.dumps(
                {
                    "completed_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "attempted": attempted,
                    "succeeded": succeeded,
                    "failed": failed
                },
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )
        temp_file.replace(
            FIRST_START_SMART_CHECK_FILE
        )
    except Exception:
        # SMART data itself has already been refreshed. Failure to write the
        # marker must not break application startup.
        pass


# startup_event() in main.py resolves this global at runtime, so replacing the
# function here changes only the startup SMART policy without duplicating any
# FastAPI routes or background monitors.
main.run_startup_smart_check = (
    run_startup_smart_check_with_first_install
)
