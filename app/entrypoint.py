import asyncio
import json
import time

from datetime import datetime, timezone
from pathlib import Path

from fastapi.responses import HTMLResponse

import main


# Runtime backend version for this image. The main module remains the core
# implementation; this entrypoint adds installation-specific startup policy.
main.app.version = "0.22.18"
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


# The static frontend currently requests the SMART full-check state once when
# the app becomes visible and then polls only for checks started manually from
# the dialog. A first-run check can therefore complete while an already-open
# browser still shows the old grey header state until F5. Inject a tiny status
# synchronizer into the root HTML response. It changes no layout or styling and
# can be removed once the same polling is folded into static/index.html.
SMART_STATUS_SYNC_SCRIPT = r"""
<script id="disk-monitor-smart-status-sync">
(() => {
    const syncSmartFullCheckStatus = async () => {
        if (document.hidden) {
            return;
        }

        try {
            const response = await fetch(
                "/api/smart/full-check",
                { cache: "no-store" }
            );

            if (!response.ok) {
                return;
            }

            const checkState = await response.json();

            if (
                typeof window.applySmartFullCheckState
                === "function"
            ) {
                window.applySmartFullCheckState(
                    checkState
                );
            }
        }
        catch (_) {
            // Container restarts can temporarily make the API unavailable.
            // The next interval retries automatically.
        }
    };

    syncSmartFullCheckStatus();
    window.setInterval(
        syncSmartFullCheckStatus,
        2000
    );
})();
</script>
"""

try:
    _index_html = (
        main.STATIC_DIR / "index.html"
    ).read_text(
        encoding="utf-8"
    )

    if (
        "disk-monitor-smart-status-sync"
        not in _index_html
    ):
        _index_html = _index_html.replace(
            "</body>",
            SMART_STATUS_SYNC_SCRIPT
            + "\n</body>",
            1
        )
except Exception:
    _index_html = None


@app.middleware("http")
async def serve_root_with_smart_status_sync(
    request,
    call_next
):
    """Keep the SMART header/result state live across backend restarts."""

    if (
        request.method == "GET"
        and request.url.path == "/"
        and _index_html is not None
    ):
        return HTMLResponse(
            content=_index_html,
            headers={
                "Cache-Control": "no-store"
            }
        )

    return await call_next(
        request
    )


def can_refresh_filesystem_usage_after_explicit_wake(
    disks
):
    """Allow capacity refresh while an HDD is explicitly held awake.

    Normal monitoring keeps the original no-wake behavior. The extra path is
    only active for HDDs that a manual/first-run SMART action has deliberately
    marked awake through main.manual_awake_until.
    """

    if not disks:
        return False

    for disk in disks:
        disk_type = (
            disk.get("type")
            or "UNKNOWN"
        )

        if disk_type not in (
            "HDD",
            "UNKNOWN"
        ):
            continue

        device = disk.get("device")
        awake_until = (
            main.manual_awake_until.get(
                device,
                0
            )
            if device
            else 0
        )

        if time.time() < awake_until:
            continue

        activity = (
            disk.get("activity")
            or {}
        )

        if activity.get("status") == "ACTIVE":
            continue

        if disk.get("current_access"):
            continue

        return False

    return True


# Keep the normal no-wake capacity policy, but recognize the explicit awake
# hold that already exists for manual/full SMART actions.
main.can_refresh_filesystem_usage_without_wake = (
    can_refresh_filesystem_usage_after_explicit_wake
)


async def seed_first_run_storage_usage():
    """Populate used/total capacity while first-run disks are already awake."""

    disk_list = await asyncio.to_thread(
        main.get_disks
    )

    # The full SMART worker deliberately woke HDDs. Refresh the explicit awake
    # hold so statvfs can seed the capacity cache immediately after the check.
    now = time.time()

    for disk in disk_list:
        if (
            (disk.get("type") or "UNKNOWN")
            in ("HDD", "UNKNOWN")
        ):
            device = disk.get("device")
            if device:
                main.manual_awake_until[
                    device
                ] = now + 120

    return await asyncio.to_thread(
        main.get_storage_usage_summary,
        disk_list
    )


async def run_startup_smart_check_with_first_install():
    """Run one full SMART check on a fresh installation.

    The first installation check intentionally uses the same full-check state
    machinery as the manual SMART CHECK. This means the header status and the
    per-drive result list are populated automatically after the first run.

    While those drives are deliberately awake, Disk Monitor also seeds the
    filesystem usage cache so "used" capacity is available immediately in the
    summary and individual drive cards.

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

    storage_usage_seeded = False

    try:
        storage_usage = (
            await seed_first_run_storage_usage()
        )
        storage_usage_seeded = bool(
            isinstance(storage_usage, dict)
            and storage_usage.get("available")
        )
    except Exception:
        # SMART initialization has already succeeded. A capacity-read failure
        # must not prevent the application from starting.
        storage_usage_seeded = False

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
                    "full_check_state": True,
                    "storage_usage_seeded":
                        storage_usage_seeded
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
