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
app.version = "0.22.38"
entrypoint.main.app.version = "0.22.38"

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

            current_is_standby = _is_standby_status(
                current_status
            )
            previous_was_standby = _is_standby_status(
                previous_status
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

                new_entry = {
                    "status": current_status,
                    "standby_since": standby_since
                }

            else:
                new_entry = {
                    "status": current_status,
                    "standby_since": None
                }
                standby_since = None

            if previous != new_entry:
                by_disk[key] = new_entry
                changed = True

            if standby_since:
                disk["standby_since"] = standby_since
                power_state[
                    "standby_since"
                ] = standby_since

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
        '"v0.32.98"',
        1,
    )

    if 'email-notifications.js?v=0.32.98' not in entrypoint._index_html:
        entrypoint._index_html = entrypoint._index_html.replace(
            '</body>',
            '<script src="/email-notifications.js?v=0.32.98"></script>\n</body>',
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
