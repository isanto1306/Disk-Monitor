import asyncio
import json

from datetime import datetime, timezone
from pathlib import Path

import main


# Runtime backend version for this image. The main module remains the core
# implementation; this entrypoint adds installation-specific startup policy.
main.app.version = "0.22.16"
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
    """Run one full SMART check on a fresh installation.

    The first installation check intentionally uses the same full-check state
    machinery as the manual SMART CHECK. This means the header status and the
    per-drive result list are populated automatically after the first run.

    Sleeping HDDs may be woken for this one-time initialization. Ordinary
    application restarts continue to use the original no-wake startup policy.
    """

    first_install = (
        CACHE_WAS_EMPTY_AT_PROCESS_START
        and not FIRST_START_SMART_CHECK_FILE.exists()
    )

    # Migration for 0.22.15: that version wrote the first-start marker and
    # refreshed SMART data, but did not populate the persistent full-check
    # state used by the SMART CHECK button/dialog. Run the corrected check once
    # when such a marker exists without a saved full-check result.
    legacy_first_start_without_full_state = (
        FIRST_START_SMART_CHECK_FILE.exists()
        and not main.SMART_FULL_CHECK_STATE_FILE.exists()
    )

    if not (
        first_install
        or legacy_first_start_without_full_state
    ):
        await _original_startup_smart_check()
        return

    # Give /dev and sysfs a short moment to settle after container startup.
    await asyncio.sleep(3)

    # Use the same worker as the manual SMART CHECK. It intentionally wakes
    # mechanical HDDs, stores per-drive success/error results, updates the
    # global header status, and persists smart_full_check_state.json.
    await asyncio.to_thread(
        main.smart_full_check_worker
    )

    state = main.get_smart_full_check_state()
    results = (
        state.get("results")
        if isinstance(state, dict)
        else None
    )
    results = (
        results
        if isinstance(results, list)
        else []
    )

    # If no devices were visible yet, do not mark initialization as complete.
    # A later process start can try again.
    if not results:
        return

    attempted = []
    succeeded = []
    failed = []

    for result in results:
        if not isinstance(result, dict):
            continue

        device = result.get("device")
        if not device:
            continue

        attempted.append(device)

        if result.get("success"):
            succeeded.append(device)
        else:
            failed.append(
                {
                    "device": device,
                    "error": result.get("error")
                    or "smart-check-failed"
                }
            )

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
                    "failed": failed,
                    "full_check_state": True
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
        # The full-check state itself has already been persisted by main.py.
        # Failure to update the compatibility marker must not break startup.
        pass


# startup_event() in main.py resolves this global at runtime, so replacing the
# function here changes only the startup SMART policy without duplicating any
# FastAPI routes or background monitors.
main.run_startup_smart_check = (
    run_startup_smart_check_with_first_install
)
