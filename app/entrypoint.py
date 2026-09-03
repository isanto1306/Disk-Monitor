import asyncio
import json

from datetime import datetime, timezone
from pathlib import Path

from fastapi.responses import HTMLResponse

import main


main.app.version = "0.22.27"
app = main.app

FIRST_START_SMART_CHECK_FILE = Path(
    "/app/cache/first_start_smart_check.json"
)

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


# Runtime-only frontend additions:
# - keep first-run SMART status live without F5;
# - once the closed-card height has settled after the first render, keep that
#   exact height for the rest of the current layout session. SMART/USB/power
#   state changes must not make the grid move. A deliberate layout switch or
#   browser resize may establish a new baseline.
# No header/menu geometry is changed.
ROOT_HTML_RUNTIME_PATCH = r"""
<script id="disk-monitor-smart-status-sync">
(() => {
    const originalEqualizeClosedDiskCardHeights = (
        typeof window.equalizeClosedDiskCardHeights === "function"
            ? window.equalizeClosedDiskCardHeights
            : null
    );

    let lockedDiskCardHeight = null;
    let lockedCompactMode = null;
    let baselineTimer = null;
    let resizeTimer = null;
    let observedGrid = null;
    let gridStyleObserver = null;

    const getDiskGrid = () => (
        document.getElementById("diskGrid")
    );

    const getClosedCards = grid => (
        grid
            ? Array.from(
                grid.querySelectorAll(
                    ".disk-card:not(.current-access-expanded)"
                )
            )
            : []
    );

    const getCompactMode = grid => {
        const firstCard = getClosedCards(grid)[0];
        return firstCard
            ? firstCard.classList.contains("compact")
            : null;
    };

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

    const applyLockedHeight = grid => {
        if (
            !grid
            || lockedDiskCardHeight === null
        ) {
            return;
        }

        const currentHeight = readEqualHeight(
            grid
        );

        if (currentHeight === lockedDiskCardHeight) {
            return;
        }

        grid.style.setProperty(
            "--disk-card-equal-height",
            lockedDiskCardHeight + "px"
        );
    };

    const ensureGridStyleObserver = () => {
        const grid = getDiskGrid();

        if (!grid || grid === observedGrid) {
            return;
        }

        if (gridStyleObserver) {
            gridStyleObserver.disconnect();
        }

        observedGrid = grid;
        gridStyleObserver = new MutationObserver(
            () => {
                if (lockedDiskCardHeight !== null) {
                    applyLockedHeight(
                        observedGrid
                    );
                }
            }
        );

        gridStyleObserver.observe(
            grid,
            {
                attributes: true,
                attributeFilter: ["style"]
            }
        );
    };

    const captureBaseline = () => {
        ensureGridStyleObserver();

        const grid = getDiskGrid();
        const cards = getClosedCards(grid);

        if (
            !grid
            || !cards.length
            || !originalEqualizeClosedDiskCardHeights
        ) {
            return;
        }

        originalEqualizeClosedDiskCardHeights(
            grid
        );

        const measured = readEqualHeight(
            grid
        );

        if (measured === null) {
            return;
        }

        lockedDiskCardHeight = measured;
        lockedCompactMode = getCompactMode(
            grid
        );

        applyLockedHeight(
            grid
        );
    };

    const scheduleBaselineCapture = () => {
        if (baselineTimer !== null) {
            return;
        }

        baselineTimer = window.setTimeout(
            () => {
                baselineTimer = null;
                window.requestAnimationFrame(
                    () => {
                        window.requestAnimationFrame(
                            captureBaseline
                        );
                    }
                );
            },
            350
        );
    };

    const resetBaseline = () => {
        lockedDiskCardHeight = null;
        lockedCompactMode = null;

        const grid = getDiskGrid();
        if (grid) {
            grid.style.removeProperty(
                "--disk-card-equal-height"
            );
        }

        scheduleBaselineCapture();
    };

    if (originalEqualizeClosedDiskCardHeights) {
        window.equalizeClosedDiskCardHeights = grid => {
            const compactMode = getCompactMode(
                grid
            );

            if (
                lockedDiskCardHeight !== null
                && compactMode === lockedCompactMode
            ) {
                applyLockedHeight(
                    grid
                );
                return;
            }

            originalEqualizeClosedDiskCardHeights(
                grid
            );

            scheduleBaselineCapture();
        };
    }

    const maintainLockedHeight = () => {
        ensureGridStyleObserver();

        const grid = getDiskGrid();
        if (!grid) {
            return;
        }

        const compactMode = getCompactMode(
            grid
        );

        if (
            lockedDiskCardHeight !== null
            && compactMode !== null
            && lockedCompactMode !== null
            && compactMode !== lockedCompactMode
        ) {
            resetBaseline();
            return;
        }

        if (lockedDiskCardHeight !== null) {
            applyLockedHeight(
                grid
            );
            return;
        }

        if (getClosedCards(grid).length) {
            scheduleBaselineCapture();
        }
    };

    window.addEventListener(
        "resize",
        () => {
            if (resizeTimer !== null) {
                window.clearTimeout(
                    resizeTimer
                );
            }

            resizeTimer = window.setTimeout(
                () => {
                    resizeTimer = null;
                    resetBaseline();
                },
                250
            );
        }
    );

    maintainLockedHeight();
    window.setInterval(
        maintainLockedHeight,
        250
    );

    let lastAppliedSmartCheckState = null;

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
                !== "function"
            ) {
                return;
            }

            const checkStateSignature = JSON.stringify(
                checkState
            );

            if (
                checkStateSignature
                === lastAppliedSmartCheckState
            ) {
                return;
            }

            lastAppliedSmartCheckState =
                checkStateSignature;

            window.applySmartFullCheckState(
                checkState
            );
        }
        catch (_) {
            // A container restart can make the API temporarily unavailable.
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

            if not isinstance(bucket, dict):
                continue

            remove_keys = []

            for key, entry in bucket.items():
                if not isinstance(entry, dict):
                    continue

                process_name = str(
                    entry.get("process") or ""
                ).strip().lower()
                target_path = str(
                    entry.get("path") or ""
                )

                if (
                    process_name == "smartctl"
                    and target_path.startswith("/dev/")
                ):
                    remove_keys.append(key)

            for key in remove_keys:
                bucket.pop(key, None)

            if not bucket:
                main.current_process_access.pop(
                    device,
                    None
                )

    except Exception:
        pass


main.update_process_access = (
    update_process_access_without_full_check_smartctl
)


async def seed_first_run_storage_usage():
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

    return await asyncio.to_thread(
        main.get_storage_usage_summary,
        disk_list
    )


async def run_startup_smart_check_with_first_install():
    first_install = (
        CACHE_WAS_EMPTY_AT_PROCESS_START
        and not FIRST_START_SMART_CHECK_FILE.exists()
    )

    if not first_install:
        await _original_startup_smart_check()
        return

    await asyncio.sleep(3)

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
        storage_usage = await seed_first_run_storage_usage()
        storage_usage_seeded = bool(
            isinstance(storage_usage, dict)
            and storage_usage.get("available")
        )
    except Exception:
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
                    "storage_usage_seeded": storage_usage_seeded
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
        pass


main.run_startup_smart_check = (
    run_startup_smart_check_with_first_install
)
