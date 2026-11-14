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
app.version = "0.22.43"
entrypoint.main.app.version = "0.22.43"

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
        '"v0.32.105"',
        1,
    )

    beta13_layout_patch = r"""
<style id="disk-monitor-beta13-layout">
/*
 * Beta 14:
 * FR/PT/ES USB-HDD cards need a little more room for the longer
 * auto-standby hint. Only the bottom edge grows; existing content
 * positions, widths and typography remain unchanged.
 */
html:lang(fr) .disk-column > .disk-card:not(.current-access-expanded),
html:lang(pt) .disk-column > .disk-card:not(.current-access-expanded),
html:lang(es) .disk-column > .disk-card:not(.current-access-expanded) {
    height: calc(var(--disk-card-equal-height) + 12px);
}

html:lang(fr) .disk-column > .disk-card.compact:not(.current-access-expanded),
html:lang(pt) .disk-column > .disk-card.compact:not(.current-access-expanded),
html:lang(es) .disk-column > .disk-card.compact:not(.current-access-expanded) {
    height: calc(var(--disk-card-equal-height) + 8px);
}

/*
 * Keep the SMART label in its native place and center the status badge
 * directly beneath it. For the normal OK state this aligns OK with SMART
 * without changing the Watt block or the left POWER section.
 */
.disk-card
.disk-footer > .footer-section:last-child {
    display: flex;
    flex-direction: column;
    align-items: center;
}
</style>
"""

    if (
        "disk-monitor-beta13-layout"
        not in entrypoint._index_html
    ):
        entrypoint._index_html = entrypoint._index_html.replace(
            "</head>",
            beta13_layout_patch
            + "\n</head>",
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

    active_since_patch = r"""
<script id="disk-monitor-active-since">
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
         * so the raw tracker cannot create an ACTIVE timestamp for them.
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
        "disk-monitor-active-since"
        not in entrypoint._index_html
    ):
        entrypoint._index_html = entrypoint._index_html.replace(
            "</body>",
            active_since_patch
            + "\n</body>",
            1,
        )


    live_power_beta_patch = r"""
<style id="disk-monitor-live-power-beta12-style">
.power-estimate-live {
    display: inline-flex;
    align-items: center;
    justify-content: flex-start;
    gap: 0.25rem;
    margin-left: 0.55rem;
    width: 6.9rem;
    min-width: 6.9rem;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1;
    opacity: 0.9;
}

.standby-since-time {
    font-variant-numeric: tabular-nums;
    font-feature-settings: "tnum" 1;
}

/*
 * Beta 7: keep Status / seit-wartet / Watt in fixed columns.
 * The Watt slot no longer moves when the time text appears or disappears.
 */
.disk-card:not(.compact):not(.current-access-expanded)
.disk-footer {
    display: grid;
    grid-template-columns: minmax(0, 1fr) max-content;
    align-items: start;
    column-gap: 20px;
}

.disk-card:not(.compact):not(.current-access-expanded)
.disk-footer > .footer-section:first-child {
    min-width: 0;
}

.disk-card:not(.compact):not(.current-access-expanded)
.power-status-row {
    position: relative;
    display: flex;
    align-items: center;
    gap: 7px;
    width: 100%;
    min-width: 0;
    padding-right: 7.4rem;
    box-sizing: border-box;
    flex-wrap: nowrap;
}

.disk-card:not(.compact):not(.current-access-expanded)
.power-status-row > .standby-since-time {
    margin-top: 0;
    margin-left: auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
}

.disk-card:not(.compact):not(.current-access-expanded)
.power-status-row > .power-estimate-live {
    position: absolute;
    top: 50%;
    right: 0;
    transform: translateY(-50%);
    display: grid;
    grid-template-columns: 1rem 5.65rem;
    align-items: center;
    column-gap: 0.25rem;
    width: 6.9rem;
    min-width: 6.9rem;
    margin-left: 0;
}

.disk-card:not(.compact):not(.current-access-expanded)
.power-status-row > .power-estimate-live > span:first-child {
    width: 1rem;
    text-align: left;
}

.disk-card:not(.compact):not(.current-access-expanded)
.power-status-row > .power-estimate-live > span:last-child {
    width: 5.65rem;
    text-align: left;
    white-space: nowrap;
}

/*
 * Beta 12: only the Watt indicator moves. SMART label and SMART badge stay
 * exactly where the native card layout puts them.
 */
.disk-card
.disk-footer > .footer-section:last-child {
    position: relative;
}

.disk-card
.disk-footer > .footer-section:last-child > .power-estimate-live {
    position: absolute;
    z-index: 1;
    display: grid;
    grid-template-columns: 0.8rem 4.4rem;
    align-items: center;
    column-gap: 0.2rem;
    width: 5.4rem;
    min-width: 5.4rem;
    margin: 0;
    font-size: 13px;
    line-height: 1;
    white-space: nowrap;
}

.disk-card
.disk-footer > .footer-section:last-child > .power-estimate-live > span:first-child {
    width: 0.8rem;
    text-align: left;
}

.disk-card
.disk-footer > .footer-section:last-child > .power-estimate-live > span:last-child {
    width: 4.4rem;
    text-align: left;
    white-space: nowrap;
}

/*
 * The native USB timer / ETA hint remains unchanged below the power row.
 */
</style>
<script id="disk-monitor-live-power-beta12">
(() => {
    if (
        typeof renderStandbySince !== "function"
        || typeof escapeHtml !== "function"
    ) {
        return;
    }

    const originalRenderStandbySinceWithPower =
        renderStandbySince;

    state.powerEstimateByRaid = {};

    if (
        typeof syncStandbySinceTracking
        === "function"
    ) {
        const originalSyncStandbySinceWithPower =
            syncStandbySinceTracking;

        syncStandbySinceTracking = function(disks) {
            const rows = Array.isArray(disks)
                ? disks
                : [];

            originalSyncStandbySinceWithPower(
                disks
            );

            const building = {};

            rows.forEach(disk => {
                if (
                    !disk
                    || typeof disk !== "object"
                ) {
                    return;
                }

                const estimate = (
                    disk.power_estimate
                    && typeof disk.power_estimate
                    === "object"
                    && disk.power_estimate.available
                )
                    ? disk.power_estimate
                    : null;

                const memberships = (
                    Array.isArray(
                        disk.raid_memberships
                    )
                        ? disk.raid_memberships
                        : []
                );

                memberships.forEach(raid => {
                    if (
                        !raid
                        || typeof raid !== "object"
                    ) {
                        return;
                    }

                    const raidDevice = String(
                        raid.device
                        || ""
                    );

                    if (!raidDevice) {
                        return;
                    }

                    if (!building[raidDevice]) {
                        const expectedMembers = (
                            Array.isArray(
                                raid.physical_members
                            )
                                ? raid.physical_members.length
                                : 0
                        );

                        building[raidDevice] = {
                            expectedMembers,
                            members: new Set(),
                            availableMembers: 0,
                            watts: 0,
                            qualifiers: []
                        };
                    }

                    const bucket =
                        building[raidDevice];

                    const memberKey = String(
                        disk.device
                        || disk.stable_id
                        || ""
                    );

                    if (
                        !memberKey
                        || bucket.members.has(
                            memberKey
                        )
                    ) {
                        return;
                    }

                    bucket.members.add(
                        memberKey
                    );

                    if (!estimate) {
                        return;
                    }

                    const watts = Number(
                        estimate.watts
                    );

                    if (!Number.isFinite(watts)) {
                        return;
                    }

                    bucket.availableMembers += 1;
                    bucket.watts += watts;
                    bucket.qualifiers.push(
                        String(
                            estimate.qualifier
                            || "≈"
                        )
                    );
                });
            });

            const completed = {};

            Object.entries(
                building
            ).forEach(
                ([raidDevice, bucket]) => {
                    const expected = (
                        bucket.expectedMembers
                        || bucket.members.size
                    );

                    if (
                        expected <= 0
                        || bucket.members.size
                            < expected
                        || bucket.availableMembers
                            < expected
                    ) {
                        return;
                    }

                    completed[raidDevice] = {
                        available: true,
                        watts: bucket.watts,
                        qualifier: (
                            bucket.qualifiers.length
                            && bucket.qualifiers.every(
                                value => value === "≤"
                            )
                                ? "≤"
                                : "≈"
                        ),
                        mode: "raid-sum",
                        source: "raid-members",
                        estimated: true
                    };
                }
            );

            state.powerEstimateByRaid =
                completed;
        };
    }

    const powerNote = () => {
        const raw = (
            document.documentElement.lang
            || navigator.language
            || "en"
        ).toLowerCase();

        if (raw.startsWith("de")) {
            return "Geschätzt bzw. Power-State-Grenzwert, nicht elektrisch gemessen";
        }
        if (raw.startsWith("fr")) {
            return "Estimation ou limite d'état d'alimentation, non mesurée électriquement";
        }
        if (raw.startsWith("pt")) {
            return "Estimativa ou limite do estado de energia, não medida eletricamente";
        }
        if (raw.startsWith("es")) {
            return "Estimación o límite del estado de energía, no medido eléctricamente";
        }

        return "Estimated or power-state limit, not electrically measured";
    };

    const formatPowerWatts = value => {
        const numeric = Number(value);

        if (!Number.isFinite(numeric)) {
            return "";
        }

        let maximumFractionDigits = 1;

        if (numeric < 1) {
            maximumFractionDigits = 3;
        }
        else if (numeric < 10) {
            maximumFractionDigits = 2;
        }

        try {
            return new Intl.NumberFormat(
                document.documentElement.lang
                || navigator.language
                || undefined,
                {
                    maximumFractionDigits,
                    minimumFractionDigits: 0
                }
            ).format(numeric);
        }
        catch (_) {
            return String(numeric);
        }
    };

    const renderPowerEstimate = disk => {
        let estimate = (
            disk
            && typeof disk === "object"
            && disk.power_estimate
            && typeof disk.power_estimate === "object"
        )
            ? disk.power_estimate
            : null;

        const device = String(
            (
                disk
                && typeof disk === "object"
                    ? disk.device
                    : ""
            )
            || ""
        );

        if (
            (
                !estimate
                || !estimate.available
            )
            && device.startsWith("md")
            && state.powerEstimateByRaid
            && state.powerEstimateByRaid[
                device
            ]
        ) {
            estimate =
                state.powerEstimateByRaid[
                    device
                ];
        }

        if (
            !estimate
            || !estimate.available
        ) {
            const diskType = String(
                (
                    disk
                    && typeof disk === "object"
                        ? disk.type
                        : ""
                )
                || ""
            ).toUpperCase();

            /*
             * Flash / SD media has no live electrical measurement here.
             * Show an explicit approximate zero instead of a dash so the
             * fixed Watt slot remains visually complete.
             */
            const unavailableValue = (
                diskType === "FLASH"
                    ? "≈ 0 W"
                    : "—"
            );

            return `
                <span
                    class="power-estimate-live"
                    title="${escapeHtml(powerNote())}"
                >
                    <span aria-hidden="true">⚡</span>
                    <span>${escapeHtml(unavailableValue)}</span>
                </span>
            `;
        }

        const formatted = formatPowerWatts(
            estimate.watts
        );

        if (!formatted) {
            return "";
        }

        const qualifier = String(
            estimate.qualifier
            || "≈"
        );

        return `
            <span
                class="power-estimate-live"
                title="${escapeHtml(powerNote())}"
            >
                <span aria-hidden="true">⚡</span>
                <span>
                    ${escapeHtml(qualifier)}
                    ${escapeHtml(formatted)} W
                </span>
            </span>
        `;
    };

    renderStandbySince = function(
        disk,
        powerStatus
    ) {
        const existing = (
            originalRenderStandbySinceWithPower(
                disk,
                powerStatus
            )
            || ""
        );

        return (
            existing
            + renderPowerEstimate(
                disk
            )
        );
    };

    /*
     * Move only the Watt element beside the existing SMART badge in every
     * card mode. The badge itself is never wrapped, moved or restyled.
     */
    let powerPlacementFrame = null;

    const placePowerBesideSmart = () => {
        powerPlacementFrame = null;

        document.querySelectorAll(
            ".disk-card"
        ).forEach(card => {
            const watt = card.querySelector(
                ".power-estimate-live"
            );
            const powerRow = card.querySelector(
                ".power-status-row"
            );

            if (!watt || !powerRow) {
                return;
            }

            const smartSection = card.querySelector(
                ".disk-footer > .footer-section:last-child"
            );

            if (!smartSection) {
                return;
            }

            const smartBadge = smartSection.querySelector(
                ":scope > .status-badge"
            );

            if (!smartBadge) {
                return;
            }

            if (
                watt.parentElement
                !== smartSection
            ) {
                smartSection.appendChild(
                    watt
                );
            }

            /*
             * Keep SMART/OK untouched. Position the fixed-width Watt block
             * exactly 15 px to the left of the badge and vertically centered
             * against it.
             */
            const sectionRect =
                smartSection.getBoundingClientRect();
            const badgeRect =
                smartBadge.getBoundingClientRect();

            watt.style.right = (
                sectionRect.right
                - badgeRect.left
                + 10
            ) + "px";

            const top = (
                smartBadge.offsetTop
                + (
                    smartBadge.offsetHeight
                    - watt.offsetHeight
                ) / 2
            );

            watt.style.top =
                Math.max(
                    0,
                    top
                ) + "px";
        });
    };

    const schedulePowerPlacement = () => {
        if (
            powerPlacementFrame
            !== null
        ) {
            return;
        }

        powerPlacementFrame =
            window.requestAnimationFrame(
                placePowerBesideSmart
            );
    };

    new MutationObserver(
        schedulePowerPlacement
    ).observe(
        document.body,
        {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: [
                "class"
            ]
        }
    );

    window.addEventListener(
        "resize",
        schedulePowerPlacement
    );

    schedulePowerPlacement();
})();
</script>
"""

    if (
        "disk-monitor-live-power-beta12"
        not in entrypoint._index_html
    ):
        entrypoint._index_html = entrypoint._index_html.replace(
            "</body>",
            live_power_beta_patch
            + "\n</body>",
            1,
        )


    usb_detail_beta_patch = r"""
<style id="disk-monitor-usb-detail-beta7-style">
.usb-link-detail-row td {
    border-top: 1px solid rgba(67, 87, 107, .28);
}

.usb-link-detail-note {
    display: block;
    margin-top: 3px;
    color: var(--muted);
    font-size: 10px;
    font-weight: 500;
}

.usb-link-details-table {
    margin-top: 0;
}
</style>
<script id="disk-monitor-usb-detail-beta7">
(() => {
    if (
        typeof renderDiskDetails !== "function"
        || typeof escapeHtml !== "function"
    ) {
        return;
    }

    const originalRenderDiskDetailsWithUsb =
        renderDiskDetails;

    const usbText = key => {
        const language = (
            typeof state !== "undefined"
            && state.language
                ? state.language
                : (
                    document.documentElement.lang
                    || navigator.language
                    || "en"
                )
        ).toLowerCase();

        const translations = {
            de: {
                speed: "USB-Geschwindigkeit",
                maxPower: "Maximum Power",
                note: "USB-Descriptor · keine Live-Messung"
            },
            en: {
                speed: "USB speed",
                maxPower: "Maximum Power",
                note: "USB descriptor · not a live measurement"
            },
            fr: {
                speed: "Vitesse USB",
                maxPower: "Puissance maximale",
                note: "Descripteur USB · pas une mesure en direct"
            },
            pt: {
                speed: "Velocidade USB",
                maxPower: "Potência máxima",
                note: "Descritor USB · não é uma medição em direto"
            },
            es: {
                speed: "Velocidad USB",
                maxPower: "Potencia máxima",
                note: "Descriptor USB · no es una medición en directo"
            }
        };

        const code = language.slice(
            0,
            2
        );

        return (
            translations[code]
            || translations.en
        )[key];
    };

    const formatUsbSpeed = speedMbps => {
        const value = Number(
            speedMbps
        );

        if (!Number.isFinite(value)) {
            return "-";
        }

        if (value >= 1000) {
            const gbps = value / 1000;

            return (
                new Intl.NumberFormat(
                    document.documentElement.lang
                    || navigator.language
                    || undefined,
                    {
                        maximumFractionDigits: 1
                    }
                ).format(gbps)
                + " Gbit/s"
            );
        }

        return (
            new Intl.NumberFormat(
                document.documentElement.lang
                || navigator.language
                || undefined,
                {
                    maximumFractionDigits: 0
                }
            ).format(value)
            + " Mbit/s"
        );
    };

    const formatUsbMaximumPower = usb => {
        const watts = Number(
            usb.max_power_w
        );

        const milliamps = Number(
            usb.max_power_ma
        );

        if (
            !Number.isFinite(watts)
            && !Number.isFinite(milliamps)
        ) {
            return "-";
        }

        const wattsText = Number.isFinite(
            watts
        )
            ? (
                new Intl.NumberFormat(
                    document.documentElement.lang
                    || navigator.language
                    || undefined,
                    {
                        maximumFractionDigits: 3
                    }
                ).format(watts)
                + " W"
            )
            : "";

        const currentText = Number.isFinite(
            milliamps
        )
            ? (
                new Intl.NumberFormat(
                    document.documentElement.lang
                    || navigator.language
                    || undefined,
                    {
                        maximumFractionDigits: 0
                    }
                ).format(milliamps)
                + " mA"
            )
            : "";

        if (
            wattsText
            && currentText
        ) {
            return (
                wattsText
                + " ("
                + currentText
                + ")"
            );
        }

        return (
            wattsText
            || currentText
            || "-"
        );
    };

    const buildUsbRows = disk => {
        const usb = (
            disk
            && typeof disk === "object"
            && disk.usb_link
            && typeof disk.usb_link === "object"
        )
            ? disk.usb_link
            : null;

        if (!usb) {
            return "";
        }

        const note = escapeHtml(
            usbText("note")
        );

        return `
            <tr class="usb-link-detail-row">
                <td>
                    <div class="smart-attribute-name">
                        <span class="smart-dot"></span>
                        <span>
                            ${escapeHtml(
                                usbText("speed")
                            )}
                        </span>
                    </div>
                </td>
                <td>
                    ${escapeHtml(
                        formatUsbSpeed(
                            usb.speed_mbps
                        )
                    )}
                </td>
            </tr>
            <tr class="usb-link-detail-row">
                <td>
                    <div class="smart-attribute-name">
                        <span class="smart-dot"></span>
                        <span>
                            ${escapeHtml(
                                usbText("maxPower")
                            )}
                        </span>
                    </div>
                </td>
                <td>
                    ${escapeHtml(
                        formatUsbMaximumPower(
                            usb
                        )
                    )}
                    <span class="usb-link-detail-note">
                        ${note}
                    </span>
                </td>
            </tr>
        `;
    };

    renderDiskDetails = function(
        disk
    ) {
        originalRenderDiskDetailsWithUsb(
            disk
        );

        if (
            !disk
            || String(
                disk.transport
                || ""
            ).toLowerCase() !== "usb"
            || !disk.usb_link
        ) {
            return;
        }

        const detailsBody =
            document.getElementById(
                "diskDetailsBody"
            );

        if (!detailsBody) {
            return;
        }

        detailsBody
            .querySelectorAll(
                ".usb-link-detail-row, .usb-link-details-table"
            )
            .forEach(
                element => element.remove()
            );

        const rows = buildUsbRows(
            disk
        );

        if (!rows) {
            return;
        }

        const tbody =
            detailsBody.querySelector(
                ".smart-detail-table tbody"
            );

        if (tbody) {
            tbody.insertAdjacentHTML(
                "beforeend",
                rows
            );

            return;
        }

        const smartSection =
            detailsBody.querySelector(
                ".detail-smart"
            );

        if (!smartSection) {
            return;
        }

        const table = document.createElement(
            "table"
        );

        table.className =
            "smart-detail-table usb-link-details-table";

        table.innerHTML = `
            <thead>
                <tr>
                    <th>${escapeHtml(
                        typeof t === "function"
                            ? t("attribute")
                            : "Attribute"
                    )}</th>
                    <th>${escapeHtml(
                        typeof t === "function"
                            ? t("value")
                            : "Value"
                    )}</th>
                </tr>
            </thead>
            <tbody>
                ${rows}
            </tbody>
        `;

        const lowerControls =
            smartSection.querySelector(
                ".detail-lower-controls"
            );

        if (lowerControls) {
            smartSection.insertBefore(
                table,
                lowerControls
            );
        }
        else {
            smartSection.appendChild(
                table
            );
        }
    };
})();
</script>
"""

    if (
        "disk-monitor-usb-detail-beta7"
        not in entrypoint._index_html
    ):
        entrypoint._index_html = entrypoint._index_html.replace(
            "</body>",
            usb_detail_beta_patch
            + "\n</body>",
            1,
        )


    power_energy_history_patch = r"""
<style id="disk-monitor-power-energy-history-beta12-style">
.smart-history-power-energy-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 18px;
    margin: -2px 0 16px;
    padding: 12px 14px;
    border: 1px solid rgba(67, 87, 107, .38);
    border-radius: 9px;
    background: rgba(25, 38, 50, .58);
}

.smart-history-power-energy-copy {
    min-width: 0;
}

.smart-history-power-energy-label {
    color: var(--muted);
    font-size: 10.5px;
    font-weight: 700;
    text-transform: uppercase;
}

.smart-history-power-energy-since {
    margin-top: 4px;
    color: var(--muted);
    font-size: 10.5px;
    line-height: 1.35;
}

.smart-history-power-energy-value {
    flex: 0 0 auto;
    color: #e3ebf1;
    font-size: 17px;
    font-weight: 760;
    white-space: nowrap;
}

@media (max-width: 560px) {
    .smart-history-power-energy-row {
        align-items: flex-start;
        flex-direction: column;
        gap: 7px;
    }
}
</style>
<script id="disk-monitor-power-energy-history-beta12">
(() => {
    if (
        typeof renderSmartHistoryModal !== "function"
        || typeof smartHistoryKey !== "function"
        || typeof state === "undefined"
    ) {
        return;
    }

    const powerEnergyText = key => {
        const language = String(
            state.language
            || document.documentElement.lang
            || navigator.language
            || "en"
        ).toLowerCase().slice(0, 2);

        const translations = {
            de: {
                label: "Verbrauch (geschätzt)",
                since: "Aufzeichnung seit",
                noData: "Noch keine Verbrauchsdaten"
            },
            en: {
                label: "Energy use (estimated)",
                since: "Recording since",
                noData: "No energy data yet"
            },
            fr: {
                label: "Consommation (estimée)",
                since: "Enregistrement depuis",
                noData: "Pas encore de données de consommation"
            },
            pt: {
                label: "Consumo (estimado)",
                since: "Registo desde",
                noData: "Ainda sem dados de consumo"
            },
            es: {
                label: "Consumo (estimado)",
                since: "Registro desde",
                noData: "Aún no hay datos de consumo"
            }
        };

        return (
            translations[language]
            || translations.en
        )[key];
    };

    const formatPowerEnergy = energy => {
        const wh = Number(
            energy
            && energy.energy_wh
        );

        if (!Number.isFinite(wh)) {
            return powerEnergyText(
                "noData"
            );
        }

        const locale = (
            document.documentElement.lang
            || navigator.language
            || undefined
        );

        if (wh >= 1000) {
            return (
                "≈ "
                + new Intl.NumberFormat(
                    locale,
                    {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2
                    }
                ).format(
                    wh / 1000
                )
                + " kWh"
            );
        }

        return (
            "≈ "
            + new Intl.NumberFormat(
                locale,
                {
                    minimumFractionDigits: (
                        wh < 10
                            ? 2
                            : 1
                    ),
                    maximumFractionDigits: 2
                }
            ).format(
                wh
            )
            + " Wh"
        );
    };

    const formatRecordingStart = value => {
        if (!value) {
            return "";
        }

        const date = new Date(
            value
        );

        if (!Number.isFinite(
            date.getTime()
        )) {
            return "";
        }

        try {
            return new Intl.DateTimeFormat(
                document.documentElement.lang
                || navigator.language
                || undefined,
                {
                    dateStyle: "short",
                    timeStyle: "short"
                }
            ).format(
                date
            );
        }
        catch (_) {
            return date.toLocaleString();
        }
    };

    const injectPowerEnergyRow = () => {
        const body = document.getElementById(
            "smartHistoryModalBody"
        );

        if (!body) {
            return;
        }

        body.querySelectorAll(
            ".smart-history-power-energy-row"
        ).forEach(
            element => element.remove()
        );

        const device =
            state.smartHistoryModalDevice;

        const range =
            state.smartHistoryRange;

        if (!device || !range) {
            return;
        }

        const history =
            state.smartHistoryCache[
                smartHistoryKey(
                    device,
                    range
                )
            ];

        if (
            !history
            || typeof history !== "object"
        ) {
            return;
        }

        const energy = (
            history.power_energy
            && typeof history.power_energy
            === "object"
        )
            ? history.power_energy
            : null;

        const ranges = body.querySelector(
            ".smart-history-modal-ranges"
        );

        if (!ranges) {
            return;
        }

        const row = document.createElement(
            "div"
        );

        row.className =
            "smart-history-power-energy-row";

        const copy = document.createElement(
            "div"
        );

        copy.className =
            "smart-history-power-energy-copy";

        const label = document.createElement(
            "div"
        );

        label.className =
            "smart-history-power-energy-label";

        label.textContent =
            powerEnergyText(
                "label"
            );

        copy.appendChild(
            label
        );

        const recordingStart =
            formatRecordingStart(
                energy
                && energy.recording_started_at
            );

        if (recordingStart) {
            const since =
                document.createElement(
                    "div"
                );

            since.className =
                "smart-history-power-energy-since";

            since.textContent = (
                powerEnergyText(
                    "since"
                )
                + " "
                + recordingStart
            );

            copy.appendChild(
                since
            );
        }

        const value = document.createElement(
            "div"
        );

        value.className =
            "smart-history-power-energy-value";

        value.textContent = (
            energy
            && energy.available
                ? formatPowerEnergy(
                    energy
                )
                : powerEnergyText(
                    "noData"
                )
        );

        row.appendChild(
            copy
        );

        row.appendChild(
            value
        );

        ranges.insertAdjacentElement(
            "afterend",
            row
        );
    };

    const originalRenderSmartHistoryModal =
        renderSmartHistoryModal;

    renderSmartHistoryModal = function() {
        originalRenderSmartHistoryModal();
        injectPowerEnergyRow();
    };
})();
</script>
"""

    if (
        "disk-monitor-power-energy-history-beta12"
        not in entrypoint._index_html
    ):
        entrypoint._index_html = entrypoint._index_html.replace(
            "</body>",
            power_energy_history_patch
            + "\n</body>",
            1,
        )
