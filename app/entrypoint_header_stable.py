import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Request
from fastapi.routing import APIRoute

import entrypoint
import email_notifications


app = entrypoint.app
app.version = "0.22.42-beta.1"
entrypoint.main.app.version = "0.22.42-beta.1"

email_notifications.install(app, entrypoint.main)


STANDBY_SINCE_STATE_FILE = Path(
    "/app/cache/standby_since_state.json"
)
STANDBY_SINCE_STATE_LOCK = threading.Lock()


def _load_standby_since_state():
    try:
        if not STANDBY_SINCE_STATE_FILE.exists():
            return {"by_disk": {}}

        data = json.loads(
            STANDBY_SINCE_STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(data, dict):
            return {"by_disk": {}}

        by_disk = data.get("by_disk")
        if not isinstance(by_disk, dict):
            by_disk = {}

        return {"by_disk": by_disk}

    except Exception:
        return {"by_disk": {}}


def _save_standby_since_state():
    try:
        STANDBY_SINCE_STATE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = STANDBY_SINCE_STATE_FILE.with_suffix(
            ".tmp"
        )

        temp_file.write_text(
            json.dumps(
                STANDBY_SINCE_STATE,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            STANDBY_SINCE_STATE_FILE
        )

    except Exception:
        pass


def _standby_tracking_key(disk):
    if not isinstance(disk, dict):
        return ""

    smart = disk.get("smart")
    if not isinstance(smart, dict):
        smart = {}

    return str(
        disk.get("serial")
        or smart.get("serial_number")
        or disk.get("device")
        or ""
    ).strip()


def _is_standby_status(status):
    return status in {
        "STANDBY",
        "STANDBY_ESTIMATED"
    }


def _utc_iso_from_epoch(epoch_seconds):
    return datetime.fromtimestamp(
        float(epoch_seconds),
        timezone.utc
    ).isoformat()


def _estimated_usb_standby_since(
    disk,
    now_epoch
):
    power_state = disk.get("power_state")
    if not isinstance(power_state, dict):
        return None

    if (
        power_state.get("status")
        != "STANDBY_ESTIMATED"
    ):
        return None

    usb_config = disk.get('usb_standby_config')
    if not isinstance(usb_config, dict):
        usb_config = {}

    activity = disk.get("activity")
    if not isinstance(activity, dict):
        activity = {}

    try:
        timer_minutes = float(
            power_state.get("standby_timer_minutes")
            or usb_config.get("minutes")
            or 0
        )
        idle_seconds = float(
            power_state.get("idle_seconds")
            or activity.get("idle_seconds")
            or 0
        )
    except Exception:
        return None

    if (
        timer_minutes <= 0
        or idle_seconds < timer_minutes * 60
    ):
        return None

    standby_epoch = (
        now_epoch
        - max(
            0.0,
            idle_seconds - timer_minutes * 60
        )
    )

    return _utc_iso_from_epoch(
        standby_epoch
    )


STANDBY_SINCE_STATE = _load_standby_since_state()


def _add_persistent_standby_since(result):
    if not isinstance(result, dict):
        return result

    disks = result.get("disks")
    if not isinstance(disks, list):
        return result

    changed = False
    now_epoch = time.time()

    with STANDBY_SINCE_STATE_LOCK:
        by_disk = STANDBY_SINCE_STATE.setdefault(
            "by_disk",
            {}
        )

        for disk in disks:
            if not isinstance(disk, dict):
                continue

            key = _standby_tracking_key(
                disk
            )
            if not key:
                continue

            power_state = disk.get("power_state")
            if not isinstance(power_state, dict):
                continue

            current_status = str(
                power_state.get("status")
                or "UNKNOWN"
            )

            previous = by_disk.get(
                key
            )
            if not isinstance(previous, dict):
                previous = {}

            previous_status = str(
                previous.get("status")
                or ""
            )

            standby_since = previous.get(
                "standby_since"
            )
            active_since = previous.get(
                "active_since"
            )

            current_is_standby = _is_standby_status(
                current_status
            )
            previous_was_standby = _is_standby_status(
                previous_status
            )
            current_is_active = (
                current_status == "ACTIVE"
            )

            if current_is_standby:
                if not standby_since:
                    estimated = (
                        _estimated_usb_standby_since(
                            disk,
                            now_epoch
                        )
                    )

                    if estimated:
                        standby_since = estimated

                    elif (
                        previous_status
                        and not previous_was_standby
                    ):
                        standby_since = (
                            _utc_iso_from_epoch(
                                now_epoch
                             )
                        )

                active_since = None
                new_entry = {
                    "status": current_status,
                    "standby_since": standby_since,
                    "active_since": None
                }

            elif current_is_active:
                standby_since = None

                if not active_since:
                    active_since = (
                        _utc_iso_from_epoch(
                            now_epoch
                        )
                    )

                new_entry = {
                    "status": current_status,
                    "standby_since": None,
                    "active_since": active_since
                }

            else:
                standby_since = None
                active_since = None
                new_entry = {
                    "status": current_status,
                    "standby_since": None,
                    "active_since": None
                }

            if previous != new_entry:
                by_disk[key] = new_entry
                changed = True

            if standby_since:
                disk["standby_since"] = standby_since
                power_state[
                    "standby_since"
                ] = standby_since

            if active_since:
                disk["active_since"] = active_since
                power_state[
                    "active_since"
                ] = active_since

        if changed:
            _save_standby_since_state()

    return result


_original_disks_route = next(
    (
        route
        for route in app.router.routes
        if (
            getattr(route, "path", None)
            == "/api/disks"
            and "GET" in (
                getattr(route, "methods", set())
                or set()
            )
        )
    ),
    None
)

if _original_disks_route is not None:
    _original_disks_endpoint = (
        _original_disks_route.endpoint
    )

    def _disks_with_persistent_standby_since(
        request: Request
    ):
        result = _original_disks_endpoint(
            request
        )
        return _add_persistent_standby_since(
            result
        )

    _persistent_standby_route = APIRoute(
        path="/api/disks",
        endpoint=_disks_with_persistent_standby_since,
        methods=["GET"],
        name="disks_with_persistent_standby_since"
    )

    app.router.routes.insert(
        app.router.routes.index(
            _original_disks_route
        ),
        _persistent_standby_route
    )


# entrypoint.py injects the runtime header style before serving the root page.
# The static frontend contains a later rule with `width: 100% !important` on
# `#app > header`, so a plain `header { width: 100vw; }` cannot win the cascade.
# Replace only that injected rule with the exact selector and matching
# importance.
#
# The global background scroll lock also adds right padding equal to the
# browser scrollbar width. Since the 0.22.29+ runtime layout compensation has
# already widened the body while the scrollbar is present, that padding would
# compensate the same gap a second time when Settings/Info/modal panels lock
# the page. Skip that extra padding only when the body-width compensation is
# already active. The scroll lock itself and all panel behavior stay unchanged.
if entrypoint._index_html is not None:
    entrypoint._index_html = entrypoint._index_html.replace(
        '"v0.32.86"',
        '"v0.32.104-beta.3"',
        1,
    )

    if 'email-notifications.js?v=0.32.103' not in entrypoint._index_html:
        entrypoint._index_html = entrypoint._index_html.replace(
            '</body>',
            '<script src="/email-notifications.js?v=0.32.103"></script>\n</body>',
            1,
        )
    entrypoint._index_html = entrypoint._index_html.replace(
        "header {\n    width: 100vw;\n}",
        "#app > header {\n    width: 100vw !important;\n}",
        1,
    )

    old_scrollbar_padding = '''        if (scrollbarGap > 0) {

            const currentPaddingRight =
                Number.parseFloat(
                    window.getComputedStyle(
                        body
                    ).paddingRight
                ) || 0;

            body.style.paddingRight =
                `${currentPaddingRight + scrollbarGap}px`;

        }
'''

    new_scrollbar_padding = '''        const bodyWidthAlreadyCompensated = Boolean(
            bodyInline.width
            && bodyInline.width.includes(
                "calc(100% +"
            )
        );

        if (
            scrollbarGap > 0
            && !bodyWidthAlreadyCompensated
        ) {

            const currentPaddingRight =
                Number.parseFloat(
                    window.getComputedStyle(
                        body
                    ).paddingRight
                ) || 0;

            body.style.paddingRight =
                `${currentPaddingRight + scrollbarGap}px`;

        }
'''

    entrypoint._index_html = entrypoint._index_html.replace(
        old_scrollbar_padding,
        new_scrollbar_padding,
        1,
    )

    active_since_beta_patch = r"""
<script id="disk-monitor-active-since-beta3">
(() => {
    const ACTIVE_SINCE_STORAGE_KEY =
        "diskMonitorActiveSinceByDisk";

    if (
        typeof state === "undefined"
        || typeof syncStandbySinceTracking !== "function"
        || typeof renderStandbySince !== "function"
        || typeof getStandbyTrackingKey !== "function"
        || typeof formatStandbySinceTime !== "function"
    ) {
        return;
    }

    const loadActiveSinceTracking = () => {
        try {
            const raw = localStorage.getItem(
                ACTIVE_SINCE_STORAGE_KEY
            );

            if (!raw) {
                return {};
            }

            const parsed = JSON.parse(raw);

            return (
                parsed
                && typeof parsed === "object"
                && !Array.isArray(parsed)
            )
                ? parsed
                : {};
        }
        catch (_) {
            return {};
        }
    };

    const saveActiveSinceTracking = () => {
        try {
            localStorage.setItem(
                ACTIVE_SINCE_STORAGE_KEY,
                JSON.stringify(
                    state.activeSinceByDisk
                )
            );
        }
        catch (_) {}
    };

    state.activeSinceByDisk =
        loadActiveSinceTracking();

    const originalSyncStandbySinceTracking =
        syncStandbySinceTracking;

    syncStandbySinceTracking = function(disks) {
        const rows = Array.isArray(disks)
            ? disks
            : [];

        /*
         * Save the previous statuses BEFORE the native standby tracker
         * updates state.lastPowerStatusByDisk.
         */
        const previousStatuses = {};

        rows.forEach(disk => {
            const key = getStandbyTrackingKey(
                disk
            );

            if (!key) {
                return;
            }

            previousStatuses[key] =
                state.lastPowerStatusByDisk[
                    key
                ]
                || null;
        });

        originalSyncStandbySinceTracking(
            disks
        );

        /*
         * RAID summary cards (md*) are synthetic display rows created by
         * getDisplayDisks(). They are not part of the raw /api/disks list,
         * so Beta 2 never created an ACTIVE timestamp for them.
         *
         * Keep the native standby tracker on the untouched raw rows and add
         * only the display-only rows to ACTIVE tracking.
         */
        const activeRows = [
            ...rows
        ];

        if (
            typeof getDisplayDisks === "function"
        ) {
            const knownKeys = new Set(
                activeRows
                    .map(
                        disk =>
                            getStandbyTrackingKey(
                                disk
                            )
                    )
                    .filter(
                        Boolean
                    )
            );

            getDisplayDisks(
                rows
            ).forEach(
                disk => {
                    const key =
                        getStandbyTrackingKey(
                            disk
                        );

                    if (
                        !key
                        || knownKeys.has(
                            key
                        )
                    ) {
                        return;
                    }

                    knownKeys.add(
                        key
                    );

                    activeRows.push(
                        disk
                    );
                }
            );
        }

        let changed = false;
        const now = Date.now();

        activeRows.forEach(disk => {
            const key = getStandbyTrackingKey(
                disk
            );

            if (!key) {
                return;
            }

            const powerState =
                disk.power_state || {};

            const currentStatus =
                String(
                    powerState.status
                    || "UNKNOWN"
                );

            if (currentStatus === "ACTIVE") {
                const existingTimestamp = Number(
                    state.activeSinceByDisk[
                        key
                    ]
                );

                const backendActiveSince = (
                    disk.active_since
                    || powerState.active_since
                    || ""
                );

                const backendTimestamp =
                    backendActiveSince
                        ? Date.parse(
                            backendActiveSince
                        )
                        : Number.NaN;

                if (
                    Number.isFinite(
                        backendTimestamp
                    )
                    && backendTimestamp > 0
                ) {
                    if (
                        existingTimestamp
                        !== backendTimestamp
                    ) {
                        state.activeSinceByDisk[
                            key
                        ] = backendTimestamp;
                        changed = true;
                    }
                }
                else if (
                    !Number.isFinite(
                        existingTimestamp
                    )
                    || existingTimestamp <= 0
                ) {
                    /*
                     * No hardware ACTIVE timestamp exists. If the backend
                     * cannot provide one, start from the first observation.
                     */
                    state.activeSinceByDisk[
                        key
                    ] = now;
                    changed = true;
                }
            }
            else if (
                Object.prototype.hasOwnProperty.call(
                    state.activeSinceByDisk,
                    key
                )
            ) {
                delete state.activeSinceByDisk[
                    key
                ];
                changed = true;
            }
        });

        if (changed) {
            saveActiveSinceTracking();
        }
    };

    const originalRenderStandbySince =
        renderStandbySince;

    renderStandbySince = function(
        disk,
        powerStatus
    ) {
        const standbyHtml =
            originalRenderStandbySince(
                disk,
                powerStatus
            );

        if (standbyHtml) {
            return standbyHtml;
        }

        if (powerStatus !== "ACTIVE") {
            return "";
        }

        const key = getStandbyTrackingKey(
            disk
        );

        if (!key) {
            return "";
        }

        const timestamp = Number(
            state.activeSinceByDisk[
                key
            ]
        );

        if (
            !Number.isFinite(timestamp)
            || timestamp <= 0
        ) {
            return "";
        }

        const formattedTime =
            formatStandbySinceTime(
                timestamp
            );

        if (!formattedTime) {
            return "";
        }

        /*
         * Reuse the exact same class and translation key as STANDBY.
         * This gives identical placement/style and automatically supports
         * DE/EN/FR/PT/ES: seit/since/depuis/desde.
         */
        return `
            <span class="standby-since-time">
                ${escapeHtml(t("standbySince"))}
                ${escapeHtml(formattedTime)}
            </span>
        `;
    };
})();
</script>
"""

    if (
        "disk-monitor-active-since-beta3"
        not in entrypoint._index_html
    ):
        entrypoint._index_html = entrypoint._index_html.replace(
            "</body>",
            active_since_beta_patch
            + "\n</body>",
            1,
        )
