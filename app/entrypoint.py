import asyncio
import json

from datetime import datetime, timezone
from pathlib import Path

from fastapi.responses import HTMLResponse

import main


# Runtime backend version for this image. The main module remains the core
# implementation; this entrypoint adds installation-specific startup policy.
main.app.version = "0.22.21"
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
_original_update_process_access = main.update_process_access


# Runtime-only frontend addition:
# - keep the first-run SMART status live without F5;
# - during a full SMART check, freeze the already established normal closed-card
#   height instead of adding permanent empty space. After the check, the same
#   height becomes a temporary page-session floor so disappearing USB/SMART
#   helper rows cannot make the grid jump upward.
# No header/menu geometry or permanent card padding/min-height is changed.
ROOT_HTML_RUNTIME_PATCH = r"""
<script id="disk-monitor-smart-status-sync">
(() => {
    const originalEqualizeClosedDiskCardHeights = (
        typeof window.equalizeClosedDiskCardHeights === "function"
            ? window.equalizeClosedDiskCardHeights
            : null
    );

    let freezeDiskCardHeight = false;
    let smartCheckHeightFloor = null;

    const getDiskGrid = () => (
        document.getElementById("diskGrid")
    );

    const readEqualHeight = grid => {
        if (!grid) {
            return null;
        }

        const raw = grid.style.getPropertyValue(
            "--disk-card-equal-height"
        );
        const value = Number.parseFloat(raw);

        return Number.isFinite(value) && value > 0
            ? value
            : null;
    };

    if (originalEqualizeClosedDiskCardHeights) {
        window.equalizeClosedDiskCardHeights = grid => {
            if (freezeDiskCardHeight) {
                return;
            }

            originalEqualizeClosedDiskCardHeights(
                grid
            );

            if (
                smartCheckHeightFloor !== null
                && grid
            ) {
                const measured = readEqualHeight(
                    grid
                );

                if (
                    measured !== null
                    && measured < smartCheckHeightFloor
                ) {
                    grid.style.setProperty(
                        "--disk-card-equal-height",
                        smartCheckHeightFloor + "px"
                    );
                }
            }
        };
    }

    const beginDiskCardHeightFreeze = () => {
        if (freezeDiskCardHeight) {
            return;
        }

        const grid = getDiskGrid();

        if (
            grid
            && originalEqualizeClosedDiskCardHeights
        ) {
            originalEqualizeClosedDiskCardHeights(
                grid
            );

            const currentHeight = readEqualHeight(
                grid
            );

            if (currentHeight !== null) {
                smartCheckHeightFloor = (
                    smartCheckHeightFloor === null
                        ? currentHeight
                        : Math.max(
                            smartCheckHeightFloor,
                            currentHeight
                        )
                );
            }
        }

        freezeDiskCardHeight = true;
    };

    const endDiskCardHeightFreeze = () => {
        if (!freezeDiskCardHeight) {
            return;
        }

        freezeDiskCardHeight = false;

        const grid = getDiskGrid();
        if (
            grid
            && typeof window.equalizeClosedDiskCardHeights
                === "function"
        ) {
            window.equalizeClosedDiskCardHeights(
                grid
            );
        }
    };

    let lastRunning = null;

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
            const running = Boolean(
                checkState && checkState.running
            );

            if (running && lastRunning !== true) {
                beginDiskCardHeightFreeze();
            }
            else if (!running && lastRunning === true) {
                endDiskCardHeightFreeze();
            }

            lastRunning = running;

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
        500
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
            ROOT_HTML_RUNTIME_PATCH
            + "\n</body>",
            1
        )
except Exception:
    _index_html = None


@app.middleware("http")
async def serve_root_with_runtime_frontend_patch(
    request,
    call_next
):
    """Serve the dashboard with the small runtime status/layout fixes."""

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


def update_process_access_without_full_check_smartctl():
    """Hide Disk Monitor's own smartctl I/O during a full SMART check.

    The process-access tracker intentionally sees raw /dev file descriptors.
    During a full SMART check that can make the smartctl subprocess look like
    user/application disk activity and temporarily grow Current Access rows.
    Remove only smartctl raw-device entries while the full-check worker is
    active. Normal process attribution is otherwise untouched.
    """

    _original_update_process_access()

    try:
        if not bool(
            main.SMART_FULL_CHECK_STATE.get(
                "running"
            )
        ):
            return

        for device in list(
            main.current_process_access.keys()
        ):
            bucket = main.current_process_access.get(
                device
            )

            if not isinstance(
                bucket,
                dict
            ):
                continue

            remove_keys = []

            for key, entry in bucket.items():
                if not isinstance(
                    entry,
                    dict
                ):
                    continue

                process_name = str(
                    entry.get("process")
                    or ""
                ).strip().lower()

                target_path = str(
                    entry.get("path")
                    or ""
                )

                if (
                    process_name == "smartctl"
                    and target_path.startswith(
                        "/dev/"
                    )
                ):
                    remove_keys.append(
                        key
                    )

            for key in remove_keys:
                bucket.pop(
                    key,
                    None
                )

            if not bucket:
                main.current_process_access.pop(
                    device,
                    None
                )

    except Exception:
        # Process attribution is diagnostic only and must never interfere with
        # the disk monitor loop or the SMART check itself.
        pass


# monitor_disks() resolves update_process_access from main's globals at runtime.
# Replacing this function therefore filters only the diagnostic access list;
# it does not change disk activity counters, SMART, power state or standby.
main.update_process_access = (
    update_process_access_without_full_check_smartctl
)


async def seed_first_run_storage_usage():
    """Seed used/total capacity only inside the genuine first-run path.

    The first-run full SMART check has already deliberately woken the drives,
    so touching mounted filesystems here cannot be the event that wakes them.
    This function bypasses the normal no-wake capacity gate locally and does
    not replace or modify the normal monitoring policy.
    """

    disk_list = await asyncio.to_thread(
        main.get_disks
    )

    mountinfo_map = await asyncio.to_thread(
        main.get_host_mountinfo_map
    )

    seen_filesystems = set()

    for disk in disk_list:
        mountpoints = (
            disk.get("mountpoints")
            if isinstance(disk, dict)
            else None
        ) or []

        for mountpoint in mountpoints:
            if not mountpoint:
                continue

            filesystem_key = (
                main.get_filesystem_identity(
                    mountpoint,
                    mountinfo_map
                )
            )

            if filesystem_key in seen_filesystems:
                continue

            seen_filesystems.add(
                filesystem_key
            )

            await asyncio.to_thread(
                main.get_filesystem_usage_for_mount,
                mountpoint,
                [disk],
                filesystem_key,
                True
            )

    # Re-run the normal summarizer. The values just seeded above are now fresh
    # cache entries, so this does not need to bypass the normal no-wake gate.
    return await asyncio.to_thread(
        main.get_storage_usage_summary,
        disk_list
    )


async def run_startup_smart_check_with_first_install():
    """Run one full SMART check only on a genuinely fresh installation.

    A fresh persistent cache triggers exactly one wake-all initialization pass.
    Every later container/application start delegates to main.py's original
    no-wake startup SMART logic.
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

    # Reuse the full-check worker so the initial result is identical to a
    # manual SMART CHECK: sleeping HDDs may be woken, results are persisted,
    # and the header/per-drive check state is populated.
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
        # Failure to update the first-run marker must not break startup.
        pass


# startup_event() in main.py resolves this global at runtime. Replacing this
# one startup function changes only first-install startup policy; the scheduled
# SMART automation, history monitor and manual endpoints remain in main.py.
main.run_startup_smart_check = (
    run_startup_smart_check_with_first_install
)
