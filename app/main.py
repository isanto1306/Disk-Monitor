import asyncio
import json
import os
import re
import secrets
import sqlite3
import stat
import subprocess
import time
import threading

from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request as UrlRequest, urlopen

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware


# -------------------------------------------------
# APP
# -------------------------------------------------

app = FastAPI(
    title="Disk Monitor",
    version="0.22.14",
    docs_url=None,
    redoc_url=None,
    openapi_url=None
)


# -------------------------------------------------
# CONFIGURATION
# -------------------------------------------------

def require_private_env(
    name,
    min_length
):

    value = os.getenv(
        name
    )

    if value is None:

        raise RuntimeError(
            f"{name} must be set. Copy .env.example to .env and provide a private value."
        )

    if (
        not value
        or value.upper().startswith(
            "CHANGE_ME"
        )
    ):

        raise RuntimeError(
            f"{name} still contains a placeholder and must be changed before startup."
        )

    if len(
        value
    ) < min_length:

        raise RuntimeError(
            f"{name} must contain at least {min_length} characters."
        )

    if (
        "\n" in value
        or "\r" in value
    ):

        raise RuntimeError(
            f"{name} must not contain newline characters."
        )

    return value


def env_bool(
    name,
    default=False
):

    raw = os.getenv(
        name
    )

    if raw is None:
        return default

    return raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "on"
    }


DISK_MONITOR_USERNAME = require_private_env(
    "DISK_MONITOR_USERNAME",
    1
)

DISK_MONITOR_PASSWORD = require_private_env(
    "DISK_MONITOR_PASSWORD",
    12
)

SESSION_SECRET = require_private_env(
    "DISK_MONITOR_SESSION_SECRET",
    32
)

SESSION_HTTPS_ONLY = env_bool(
    "DISK_MONITOR_SESSION_HTTPS_ONLY",
    False
)


app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="disk_monitor_session",
    max_age=60 * 60 * 24 * 7,
    same_site="lax",
    https_only=SESSION_HTTPS_ONLY
)


@app.middleware(
    "http"
)
async def add_security_headers(
    request: Request,
    call_next
):

    response = await call_next(
        request
    )

    response.headers[
        "X-Content-Type-Options"
    ] = "nosniff"

    response.headers[
        "Referrer-Policy"
    ] = "no-referrer"

    response.headers[
        "Permissions-Policy"
    ] = (
        "camera=(), microphone=(), geolocation=()"
    )

    if request.url.path.startswith(
        "/api/"
    ):

        response.headers[
            "Cache-Control"
        ] = "no-store"

    return response


SYS_BLOCK = Path("/host/sys/block")
HOST_PROC = Path("/host/proc")
PROC_MOUNTS = HOST_PROC / "1/mounts"
STATIC_DIR = Path("/app/static")
SMART_CACHE_FILE = Path("/app/cache/smart_cache.json")
USB_POWER_CONFIG_FILE = Path("/app/cache/usb_power_config.json")
DISK_ACTIVITY_STATE_FILE = Path("/app/cache/disk_activity_state.json")
STORAGE_USAGE_CACHE_FILE = Path("/app/cache/storage_usage_cache.json")
SMART_HISTORY_DB_FILE = Path("/app/cache/smart_history.db")
SMART_FULL_CHECK_STATE_FILE = Path(
    "/app/cache/smart_full_check_state.json"
)
SMART_AUTOMATION_CONFIG_FILE = Path(
    "/app/cache/smart_automation_config.json"
)
HOST_ROOT = HOST_PROC / "1/root"
CGROUP_ROOT = Path("/sys/fs/cgroup")

SMART_FULL_CHECK_LOCK = threading.Lock()
SMART_FULL_CHECK_STATE = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "total": 0,
    "completed": 0,
    "percent": 0,
    "current_device": None,
    "results": [],
    "error": None
}

# ZimaOS Local Storage exposes the same standby state used by ZimaOS itself.
# The service is normally registered below /v2/local_storage.
ZIMAOS_GATEWAY_ROUTES_URLS = [
    value.strip()
    for value in os.getenv(
        "ZIMAOS_GATEWAY_ROUTES_URLS",
        (
            "http://127.0.0.1:39743/v1/gateway/routes,"
            "http://127.0.0.1/v1/gateway/routes"
        )
    ).split(",")
    if value.strip()
]

ZIMAOS_LOCAL_STORAGE_FALLBACK = os.getenv(
    "ZIMAOS_LOCAL_STORAGE_URL",
    "http://127.0.0.1:37819/v2/local_storage"
).rstrip("/")

ZIMAOS_ROUTE_CACHE_SECONDS = 60.0

# Exact standby choices exposed by the ZimaOS UI.
#
# ATA/hdparm standby-level encoding:
#   0   = disabled / never
#   120 = 10 minutes
#   240 = 20 minutes
#   241 = 30 minutes
#   242 = 1 hour
#   244 = 2 hours
#   246 = 3 hours
#   248 = 4 hours
#   250 = 5 hours
#
# The dashboard intentionally exposes only these ZimaOS choices instead of
# arbitrary levels.
ZIMAOS_STANDBY_ALLOWED_LEVELS = {
    0,
    120,
    240,
    241,
    242,
    244,
    246,
    248,
    250,
}

SECTOR_SIZE = 512
INTERVAL = 1.0

# Process access entries are kept briefly so the dashboard can still
# display short I/O bursts between two frontend refreshes.
PROCESS_ACCESS_TTL = 5.0

# Once a process/path has been confirmed for a disk, keep that last
# confirmed entry visible while the same physical disk still has block I/O.
# This prevents a path from flickering on/off when an application briefly
# closes and reopens its file descriptor during one continuous copy job.
#
# The path is NOT invented: only a previously confirmed /proc FD mapping is
# held. After disk I/O stops, it is removed again after this short grace time.
PROCESS_ACCESS_DISK_IO_HOLD_SECONDS = 8.0

USB_HDD_ACTIVE_HOLD_SECONDS = 10.0

DISK_ACTIVITY_STATE_SAVE_SECONDS = 5.0

# Filesystem capacity is refreshed every 30 seconds and cached.
#
# IMPORTANT NO-WAKE POLICY:
# statvfs() touches a mounted filesystem and can cause a sleeping mechanical
# disk/controller to become active. Therefore automatic usage refresh is only
# allowed while that HDD already has confirmed live block/process I/O.
# Sleeping/inactive/unknown HDDs are served strictly from cache.
STORAGE_USAGE_REFRESH_SECONDS = 30.0

# Normal monitoring must never fall back to automatic hdparm/smartctl HDD
# power probes. On ZimaOS we use the local-storage API. If that API is not
# available, normal monitoring remains passive.
ALLOW_AUTOMATIC_HDD_POWER_PROBES = False

# SMART history remains no-wake for mechanical HDDs.
SMART_HISTORY_SAFE_INTERVAL_SECONDS = 30 * 60
SMART_HISTORY_RETENTION_DAYS = 400
SMART_HISTORY_MAX_API_POINTS = 5000

# Automatic HDD SMART refresh is strictly no-wake. A read is only scheduled
# after real block I/O proves that the HDD woke naturally. Before the delayed
# read, the drive must still be confirmed awake by passive information.
SMART_AUTOMATION_ALLOWED_CHECKS_PER_DAY = {0, 1, 2, 3}
SMART_AUTOMATION_WAKE_DELAY_SECONDS = 45
SMART_AUTOMATION_POLL_SECONDS = 5
SMART_AUTOMATION_RECENT_IO_SECONDS = 8

# USB HDD monitoring is fully passive during normal dashboard operation.
# No automatic smartctl, hdparm or ZimaOS power-state query is issued for
# USB HDDs. State is derived from kernel I/O plus an optional per-drive
# expected auto-standby timer. Explicit user actions may still issue
# smartctl commands.

MAX_ACCESS_ENTRIES_PER_DISK = 8
MAX_ACCESS_PATHS_PER_PROCESS = 6

previous_stats = {}
disk_activity = {}
disk_activity_state_last_save = 0.0
smart_cache = {}
smart_history_last_auto_read = {}
manual_awake_until = {}

smart_automation_config = {
    "checks_per_day": 0,
    "completed_slots": {},
    "automatic_runs": {}
}
smart_automation_pending = {}

process_io_previous = {}
current_process_access = {}

# Successful smartctl device mode per USB HDD.
# "__auto__" means no explicit -d option is required.
power_smartctl_type_cache = {}

# Explicitly confirmed USB HDD runtime states. Normal passive monitoring
# never queries the USB bridge. Real I/O overrides these states immediately.
usb_runtime_power_state = {}

# Per-drive expected automatic standby timers. Stored by stable disk identity.
# Example: {"by-id:usb-WD_...": {"minutes": 30}}
usb_power_config = {}

# Cached filesystem usage keyed by mountpoint. This lets the dashboard keep
# showing the last known used-space value without querying sleeping HDDs.
storage_usage_cache = {}

APP_STARTED_AT = datetime.now(
    timezone.utc
).isoformat()

APP_STARTED_MONOTONIC = time.monotonic()

resource_usage = {
    "cpu_percent": 0.0,
    "memory_bytes": None,
    "memory_limit_bytes": None,
    "updated_at": None
}
resource_cpu_previous = {
    "usage_seconds": None,
    "time": None
}

zimaos_local_storage_base_url = None
zimaos_route_last_refresh = 0.0

LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 60.0
LOGIN_BLOCK_SECONDS = 60.0
LOGIN_RATE_LIMIT_LOCK = threading.Lock()
login_failures = {}


def load_smart_cache():

    global smart_cache

    try:

        if not SMART_CACHE_FILE.exists():
            smart_cache = {}
            return

        data = json.loads(
            SMART_CACHE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            dict
        ):
            smart_cache = data

        else:
            smart_cache = {}

    except Exception:
        smart_cache = {}


def save_smart_cache():

    try:

        SMART_CACHE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = SMART_CACHE_FILE.with_suffix(
            ".tmp"
        )

        temp_file.write_text(
            json.dumps(
                smart_cache,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            SMART_CACHE_FILE
        )

    except Exception:
        pass


def load_usb_power_config():

    global usb_power_config

    try:

        if not USB_POWER_CONFIG_FILE.exists():
            usb_power_config = {}
            return

        data = json.loads(
            USB_POWER_CONFIG_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            dict
        ):
            usb_power_config = data
        else:
            usb_power_config = {}

    except Exception:
        usb_power_config = {}


def save_usb_power_config():

    try:

        USB_POWER_CONFIG_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = USB_POWER_CONFIG_FILE.with_suffix(
            ".tmp"
        )

        temp_file.write_text(
            json.dumps(
                usb_power_config,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            USB_POWER_CONFIG_FILE
        )

    except Exception:
        pass



def load_smart_automation_config():

    global smart_automation_config

    default_config = {
        "checks_per_day": 0,
        "completed_slots": {},
        "automatic_runs": {}
    }

    try:

        if not SMART_AUTOMATION_CONFIG_FILE.exists():

            smart_automation_config = dict(
                default_config
            )

            return

        data = json.loads(
            SMART_AUTOMATION_CONFIG_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict
        ):

            smart_automation_config = dict(
                default_config
            )

            return

        try:

            checks_per_day = int(
                data.get(
                    "checks_per_day",
                    0
                )
            )

        except Exception:

            checks_per_day = 0

        if (
            checks_per_day
            not in SMART_AUTOMATION_ALLOWED_CHECKS_PER_DAY
        ):

            checks_per_day = 0

        completed_slots = data.get(
            "completed_slots"
        )

        if not isinstance(
            completed_slots,
            dict
        ):

            completed_slots = {}

        automatic_runs = data.get(
            "automatic_runs"
        )

        if not isinstance(
            automatic_runs,
            dict
        ):

            automatic_runs = {}

        smart_automation_config = {
            "checks_per_day":
                checks_per_day,
            "completed_slots":
                completed_slots,
            "automatic_runs":
                automatic_runs
        }

    except Exception:

        smart_automation_config = dict(
            default_config
        )


def save_smart_automation_config():

    try:

        SMART_AUTOMATION_CONFIG_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = (
            SMART_AUTOMATION_CONFIG_FILE.with_suffix(
                ".tmp"
            )
        )

        temp_file.write_text(
            json.dumps(
                smart_automation_config,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            SMART_AUTOMATION_CONFIG_FILE
        )

    except Exception:
        pass


def load_storage_usage_cache():

    global storage_usage_cache

    try:

        if not STORAGE_USAGE_CACHE_FILE.exists():

            storage_usage_cache = {}

            return

        data = json.loads(
            STORAGE_USAGE_CACHE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(
            data,
            dict
        ):

            storage_usage_cache = data

        else:

            storage_usage_cache = {}

    except Exception:

        storage_usage_cache = {}


def save_storage_usage_cache():

    try:

        STORAGE_USAGE_CACHE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        temp_file = (
            STORAGE_USAGE_CACHE_FILE.with_suffix(
                ".tmp"
            )
        )

        temp_file.write_text(
            json.dumps(
                storage_usage_cache,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            STORAGE_USAGE_CACHE_FILE
        )

    except Exception:
        pass



def get_persistable_smart_full_check_state():

    """
    Return the last completed SMART-check state in a restart-safe form.

    Running/current-device information is deliberately not persisted.
    """

    with SMART_FULL_CHECK_LOCK:

        source = json.loads(
            json.dumps(
                SMART_FULL_CHECK_STATE
            )
        )

    results = []

    for result in (
        source.get(
            "results"
        )
        or []
    ):

        if not isinstance(
            result,
            dict
        ):
            continue

        results.append(
            {
                "device":
                    result.get(
                        "device"
                    ),
                "type":
                    result.get(
                        "type"
                    ),
                "success":
                    bool(
                        result.get(
                            "success"
                        )
                    ),
                "health":
                    result.get(
                        "health"
                    ),
                "changes":
                    (
                        result.get(
                            "changes"
                        )
                        if isinstance(
                            result.get(
                                "changes"
                            ),
                            list
                        )
                        else []
                    ),
                "error":
                    result.get(
                        "error"
                    )
            }
        )

    return {
        "running": False,
        "started_at":
            source.get(
                "started_at"
            ),
        "finished_at":
            source.get(
                "finished_at"
            ),
        "total":
            int(
                source.get(
                    "total"
                )
                or len(
                    results
                )
            ),
        "completed":
            int(
                source.get(
                    "completed"
                )
                or len(
                    results
                )
            ),
        "percent": 100,
        "current_device": None,
        "results": results,
        "error":
            source.get(
                "error"
            )
    }


def save_smart_full_check_state():

    """
    Persist ONLY a completed SMART check.

    The write is atomic so an interrupted container stop cannot leave a
    half-written JSON file behind.
    """

    try:

        state = (
            get_persistable_smart_full_check_state()
        )

        if (
            not state.get(
                "finished_at"
            )
            or not state.get(
                "results"
            )
        ):
            return False

        SMART_FULL_CHECK_STATE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        payload = {
            "schema_version": 1,
            "saved_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "state": state
        }

        temp_file = (
            SMART_FULL_CHECK_STATE_FILE.with_suffix(
                ".tmp"
            )
        )

        temp_file.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            SMART_FULL_CHECK_STATE_FILE
        )

        return True

    except Exception:

        return False


def load_smart_full_check_state():

    """
    Restore the last COMPLETED manual SMART check after a restart.

    The restored state is always non-running. Therefore the last green,
    yellow or red result remains visible until the next manual check finishes.
    """

    try:

        if not SMART_FULL_CHECK_STATE_FILE.exists():
            return False

        payload = json.loads(
            SMART_FULL_CHECK_STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            payload,
            dict
        ):
            return False

        state = payload.get(
            "state"
        )

        if not isinstance(
            state,
            dict
        ):
            state = payload

        results = state.get(
            "results"
        )

        if (
            not isinstance(
                results,
                list
            )
            or not results
            or not state.get(
                "finished_at"
            )
        ):
            return False

        restored = {
            "running": False,
            "started_at":
                state.get(
                    "started_at"
                ),
            "finished_at":
                state.get(
                    "finished_at"
                ),
            "total":
                int(
                    state.get(
                        "total"
                    )
                    or len(
                        results
                    )
                ),
            "completed":
                int(
                    state.get(
                        "completed"
                    )
                    or len(
                        results
                    )
                ),
            "percent": 100,
            "current_device": None,
            "results": results,
            "error":
                state.get(
                    "error"
                )
        }

        with SMART_FULL_CHECK_LOCK:

            SMART_FULL_CHECK_STATE.update(
                restored
            )

        return True

    except Exception:

        return False


def host_mount_path(
    mountpoint
):

    if mountpoint == "/":

        return HOST_ROOT

    return (
        HOST_ROOT
        / mountpoint.lstrip(
            "/"
        )
    )


def decode_mountinfo_field(
    value
):

    # Linux mountinfo escapes spaces/tabs/newlines/backslashes as octal.
    replacements = {
        "\\040": " ",
        "\\011": "\t",
        "\\012": "\n",
        "\\134": "\\"
    }

    for encoded, decoded in replacements.items():

        value = value.replace(
            encoded,
            decoded
        )

    return value


def get_host_mountinfo_map():

    result = {}

    mountinfo_path = (
        HOST_PROC
        / "1"
        / "mountinfo"
    )

    try:

        lines = mountinfo_path.read_text(
            encoding="utf-8",
            errors="replace"
        ).splitlines()

    except Exception:

        return result

    for line in lines:

        try:

            before, after = line.split(
                " - ",
                1
            )

            fields = before.split()
            fs_fields = after.split()

            if (
                len(fields) < 6
                or len(fs_fields) < 2
            ):

                continue

            major_minor = fields[2]

            root = decode_mountinfo_field(
                fields[3]
            )

            mountpoint = decode_mountinfo_field(
                fields[4]
            )

            fs_type = fs_fields[0]

            source = decode_mountinfo_field(
                fs_fields[1]
            )

            result[
                mountpoint
            ] = {
                "major_minor": major_minor,
                "root": root,
                "fs_type": fs_type,
                "source": source
            }

        except Exception:

            continue

    return result


def get_filesystems_for_mountpoints(
    mountpoints
):

    mountinfo_map = (
        get_host_mountinfo_map()
    )

    filesystems = []

    for mountpoint in (
        mountpoints
        or []
    ):

        info = mountinfo_map.get(
            mountpoint
        )

        if not info:
            continue

        fs_type = (
            info.get(
                "fs_type"
            )
            or ""
        ).strip()

        if (
            fs_type
            and fs_type not in filesystems
        ):

            filesystems.append(
                fs_type
            )

    return filesystems




def get_filesystem_identity(
    mountpoint,
    mountinfo_map
):

    info = mountinfo_map.get(
        mountpoint
    )

    if info:

        major_minor = (
            info.get(
                "major_minor"
            )
            or ""
        )

        source = (
            info.get(
                "source"
            )
            or ""
        )

        fs_type = (
            info.get(
                "fs_type"
            )
            or ""
        )

        # Bind mounts of the same filesystem share the same major:minor.
        # Include source/fs type as additional protection for pseudo filesystems.
        return (
            f"{major_minor}|"
            f"{fs_type}|"
            f"{source}"
        )

    # No-wake fallback: never stat() the mounted filesystem merely to build
    # an identity. If mountinfo is unavailable, use the mountpoint string.
    return (
        f"mount:{mountpoint}"
    )



def can_refresh_filesystem_usage_without_wake(
    disks
):

    """
    Refresh filesystem usage only when a mechanical HDD is already doing
    real I/O. This keeps statvfs from becoming the event that wakes the disk
    or resets its idle timer.

    SSD/NVMe/FLASH are safe here. HDD/UNKNOWN require confirmed block I/O or
    a confirmed current process/FD access.
    """

    if not disks:
        return False

    for disk in disks:

        disk_type = (
            disk.get(
                "type"
            )
            or "UNKNOWN"
        )

        if disk_type not in (
            "HDD",
            "UNKNOWN"
        ):
            continue

        activity = (
            disk.get(
                "activity"
            )
            or {}
        )

        if (
            activity.get(
                "status"
            )
            == "ACTIVE"
        ):
            continue

        if disk.get(
            "current_access"
        ):
            continue

        return False

    return True


def get_filesystem_usage_for_mount(
    mountpoint,
    disks,
    filesystem_key,
    allow_refresh
):

    now = time.time()

    cache_key = (
        "filesystem:"
        + filesystem_key
    )

    cached = storage_usage_cache.get(
        cache_key
    )

    # Backward compatibility with the old mountpoint-keyed cache.
    if not isinstance(
        cached,
        dict
    ):

        cached = storage_usage_cache.get(
            mountpoint
        )

    cached_at = None

    if isinstance(
        cached,
        dict
    ):

        try:

            cached_at = float(
                cached.get(
                    "cached_at",
                    0
                )
            )

        except Exception:

            cached_at = 0

        if (
            cached_at
            and (
                now
                - cached_at
            ) < STORAGE_USAGE_REFRESH_SECONDS
        ):

            return {
                **cached,
                "cached": True,
                "filesystem_key":
                    filesystem_key
            }

    # Never touch an idle/sleeping HDD mount just to update capacity.
    if not allow_refresh:

        if isinstance(
            cached,
            dict
        ):

            return {
                **cached,
                "cached": True,
                "refresh_skipped_no_wake": True,
                "filesystem_key":
                    filesystem_key
            }

        return None

    try:

        host_path = host_mount_path(
            mountpoint
        )

        stats = os.statvfs(
            host_path
        )

        total_bytes = (
            stats.f_blocks
            * stats.f_frsize
        )

        available_bytes = (
            stats.f_bavail
            * stats.f_frsize
        )

        free_bytes = (
            stats.f_bfree
            * stats.f_frsize
        )

        # Same df-style "used" definition: total - all free blocks.
        used_bytes = max(
            0,
            total_bytes
            - free_bytes
        )

        result = {
            "filesystem_key":
                filesystem_key,
            "mountpoint": mountpoint,
            "total_bytes": int(
                total_bytes
            ),
            "used_bytes": int(
                used_bytes
            ),
            "available_bytes": int(
                available_bytes
            ),
            "cached_at": now
        }

        storage_usage_cache[
            cache_key
        ] = result

        save_storage_usage_cache()

        return {
            **result,
            "cached": False
        }

    except Exception:

        if isinstance(
            cached,
            dict
        ):

            return {
                **cached,
                "cached": True,
                "filesystem_key":
                    filesystem_key
            }

        return None


def get_storage_usage_summary(
    disk_list
):

    for disk in disk_list:

        disk[
            "storage_usage"
        ] = {
            "available": False,
            "used_bytes": None,
            "total_bytes": None,
            "cached": True,
            "updated_at": None,
            "refresh_skipped_no_wake": False
        }

    mountinfo_map = (
        get_host_mountinfo_map()
    )

    filesystems = {}

    for disk in disk_list:

        for mountpoint in (
            disk.get(
                "mountpoints"
            )
            or []
        ):

            if not mountpoint:
                continue

            filesystem_key = (
                get_filesystem_identity(
                    mountpoint,
                    mountinfo_map
                )
            )

            entry = filesystems.setdefault(
                filesystem_key,
                {
                    "mountpoints": [],
                    "disks": []
                }
            )

            if (
                mountpoint
                not in entry[
                    "mountpoints"
                ]
            ):

                entry[
                    "mountpoints"
                ].append(
                    mountpoint
                )

            if (
                disk
                not in entry[
                    "disks"
                ]
            ):

                entry[
                    "disks"
                ].append(
                    disk
                )

    used_bytes = 0
    filesystem_total_bytes = 0
    known_filesystems = 0
    missing_filesystems = 0
    cached_filesystems = 0

    filesystem_details = []

    for filesystem_key, entry in sorted(
        filesystems.items()
    ):

        mountpoints = (
            entry[
                "mountpoints"
            ]
        )

        if not mountpoints:

            continue

        # One representative mountpoint per unique filesystem.
        mountpoint = sorted(
            mountpoints,
            key=lambda value: (
                len(value),
                value
            )
        )[0]

        allow_refresh = (
            can_refresh_filesystem_usage_without_wake(
                entry[
                    "disks"
                ]
            )
        )

        usage = (
            get_filesystem_usage_for_mount(
                mountpoint,
                entry[
                    "disks"
                ],
                filesystem_key,
                allow_refresh
            )
        )

        if not usage:

            missing_filesystems += 1

            continue

        known_filesystems += 1

        if usage.get(
            "cached"
        ):

            cached_filesystems += 1

        current_used = int(
            usage.get(
                "used_bytes",
                0
            )
            or 0
        )

        current_total = int(
            usage.get(
                "total_bytes",
                0
            )
            or 0
        )

        used_bytes += current_used

        filesystem_total_bytes += (
            current_total
        )

        updated_at = None

        try:

            cached_at_value = float(
                usage.get(
                    "cached_at",
                    0
                )
                or 0
            )

            if cached_at_value > 0:

                updated_at = datetime.fromtimestamp(
                    cached_at_value,
                    timezone.utc
                ).isoformat()

        except Exception:

            updated_at = None

        usage_payload = {
            "available": True,
            "used_bytes":
                current_used,
            "total_bytes":
                current_total,
            "cached": bool(
                usage.get(
                    "cached"
                )
            ),
            "updated_at":
                updated_at,
            "refresh_skipped_no_wake": bool(
                usage.get(
                    "refresh_skipped_no_wake"
                )
            ),
            "filesystem_key":
                filesystem_key,
            "mountpoint":
                mountpoint
        }

        for disk in entry[
            "disks"
        ]:

            disk[
                "storage_usage"
            ] = dict(
                usage_payload
            )

        filesystem_details.append(
            {
                "filesystem_key":
                    filesystem_key,
                "mountpoint":
                    mountpoint,
                "mountpoints":
                    mountpoints,
                "used_bytes":
                    current_used,
                "total_bytes":
                    current_total,
                "cached": bool(
                    usage.get(
                        "cached"
                    )
                ),
                "updated_at":
                    updated_at,
                "refresh_skipped_no_wake": bool(
                    usage.get(
                        "refresh_skipped_no_wake"
                    )
                )
            }
        )

    return {
        "available": (
            known_filesystems > 0
        ),
        "used_bytes":
            used_bytes,
        "filesystem_total_bytes":
            filesystem_total_bytes,
        "known_filesystems":
            known_filesystems,
        "missing_filesystems":
            missing_filesystems,
        "complete": (
            missing_filesystems == 0
            and known_filesystems > 0
        ),
        "cached_filesystems":
            cached_filesystems,
        "refresh_seconds":
            STORAGE_USAGE_REFRESH_SECONDS,
        "deduplicated":
            True,
        "identity_source":
            "host-mountinfo-major-minor",
        "usage_source":
            "statvfs",
        "no_wake_policy":
            True,
        "filesystems":
            filesystem_details
    }



def get_by_id_name_for_device(
    device
):

    by_id_dir = Path(
        "/dev/disk/by-id"
    )

    if not by_id_dir.exists():
        return None

    target = os.path.realpath(
        f"/dev/{device}"
    )

    matches = []

    try:

        for entry in by_id_dir.iterdir():

            name = entry.name

            if "-part" in name:
                continue

            try:

                resolved = os.path.realpath(
                    str(entry)
                )

            except Exception:
                continue

            if resolved != target:
                continue

            priority = 50

            if name.startswith(
                "wwn-"
            ):
                priority = 10

            elif name.startswith(
                "ata-"
            ):
                priority = 20

            elif name.startswith(
                "usb-"
            ):
                priority = 30

            matches.append(
                (
                    priority,
                    len(name),
                    name
                )
            )

    except Exception:
        return None

    if not matches:
        return None

    matches.sort()

    return matches[0][2]


def get_disk_stable_id(
    device,
    device_path,
    model=None,
    vendor=None,
    serial=None,
    size_bytes=None
):

    by_id_name = (
        get_by_id_name_for_device(
            device
        )
    )

    if by_id_name:
        return (
            "by-id:"
            + by_id_name
        )

    wwid = (
        read_file(
            device_path / "device/wwid"
        )
        or read_file(
            device_path / "wwid"
        )
    )

    if wwid:
        return (
            "wwid:"
            + wwid.strip()
        )

    if serial:

        model_text = (
            model
            or ""
        ).strip()

        return (
            "serial:"
            + model_text
            + ":"
            + serial.strip()
        )

    return (
        "fallback:"
        + (vendor or "").strip()
        + ":"
        + (model or "").strip()
        + ":"
        + str(
            int(
                size_bytes
                or 0
            )
        )
        + ":"
        + device
    )


def get_usb_standby_config(
    stable_id
):

    configured = usb_power_config.get(
        stable_id
    )

    minutes = None

    if isinstance(
        configured,
        dict
    ):

        raw_minutes = configured.get(
            "minutes"
        )

        try:

            if raw_minutes is not None:

                parsed = int(
                    raw_minutes
                )

                if 1 <= parsed <= 1440:
                    minutes = parsed

        except Exception:
            minutes = None

    return {
        "minutes": minutes,
        "configured": (
            minutes is not None
        )
    }


def set_usb_standby_config(
    stable_id,
    minutes
):

    if minutes is None:

        usb_power_config.pop(
            stable_id,
            None
        )

    else:

        usb_power_config[
            stable_id
        ] = {
            "minutes": int(
                minutes
            )
        }

    save_usb_power_config()


def get_activity_idle_seconds(
    activity
):

    idle_since = activity.get(
        "idle_since"
    )

    if not idle_since:
        return 0.0

    try:

        idle_time = datetime.fromisoformat(
            idle_since
        )

        if idle_time.tzinfo is None:

            idle_time = idle_time.replace(
                tzinfo=timezone.utc
            )

        return max(
            0.0,
            (
                datetime.now(
                    timezone.utc
                )
                - idle_time
            ).total_seconds()
        )

    except Exception:
        return 0.0


def get_current_boot_id():

    try:

        boot_id = Path(
            "/proc/sys/kernel/random/boot_id"
        ).read_text(
            encoding="utf-8"
        ).strip()

        return boot_id or None

    except Exception:
        return None


def load_disk_activity_state():

    global previous_stats
    global disk_activity

    try:

        if not DISK_ACTIVITY_STATE_FILE.exists():
            return

        data = json.loads(
            DISK_ACTIVITY_STATE_FILE.read_text(
                encoding="utf-8"
            )
        )

        if not isinstance(
            data,
            dict
        ):
            return

        saved_boot_id = data.get(
            "boot_id"
        )

        current_boot_id = (
            get_current_boot_id()
        )

        # Disk counters reset on reboot, so never reuse the saved state
        # across different host boots.
        if (
            saved_boot_id
            and current_boot_id
            and saved_boot_id
            != current_boot_id
        ):
            return

        saved_stats = data.get(
            "previous_stats"
        )

        saved_activity = data.get(
            "disk_activity"
        )

        if isinstance(
            saved_stats,
            dict
        ):

            previous_stats.update(
                {
                    str(device): value
                    for device, value
                    in saved_stats.items()
                    if isinstance(
                        value,
                        dict
                    )
                }
            )

        if isinstance(
            saved_activity,
            dict
        ):

            disk_activity.update(
                {
                    str(device): value
                    for device, value
                    in saved_activity.items()
                    if isinstance(
                        value,
                        dict
                    )
                }
            )

    except Exception:
        pass


def save_disk_activity_state(
    force=False
):

    global disk_activity_state_last_save

    now = time.time()

    if (
        not force
        and (
            now
            - disk_activity_state_last_save
        )
        < DISK_ACTIVITY_STATE_SAVE_SECONDS
    ):
        return

    try:

        DISK_ACTIVITY_STATE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        payload = {
            "boot_id":
                get_current_boot_id(),
            "saved_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "previous_stats":
                previous_stats,
            "disk_activity":
                disk_activity
        }

        temp_file = (
            DISK_ACTIVITY_STATE_FILE.with_suffix(
                ".tmp"
            )
        )

        temp_file.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        temp_file.replace(
            DISK_ACTIVITY_STATE_FILE
        )

        disk_activity_state_last_save = now

    except Exception:
        pass




# -------------------------------------------------
# MODELS
# -------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


class UsbStandbyConfigRequest(BaseModel):
    minutes: int | None = None


class ZimaOsStandbyTimerRequest(BaseModel):
    level: int


class SmartAutomationRequest(BaseModel):
    checks_per_day: int


# -------------------------------------------------
# AUTHENTICATION
# -------------------------------------------------

def is_authenticated(request: Request):

    return (
        request.session.get("authenticated")
        is True
    )


def require_auth(request: Request):

    if not is_authenticated(request):

        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )


def get_login_client_key(
    request: Request
):

    if (
        request.client
        and request.client.host
    ):

        return request.client.host

    return "unknown"


def login_rate_limited(
    client_key
):

    now = time.monotonic()

    with LOGIN_RATE_LIMIT_LOCK:

        failures = [
            timestamp
            for timestamp in login_failures.get(
                client_key,
                []
            )
            if (
                now
                - timestamp
            ) <= LOGIN_FAILURE_WINDOW_SECONDS
        ]

        login_failures[
            client_key
        ] = failures

        if len(
            failures
        ) < LOGIN_FAILURE_LIMIT:

            return False

        return (
            now
            - failures[-1]
        ) <= LOGIN_BLOCK_SECONDS


def record_login_failure(
    client_key
):

    now = time.monotonic()

    with LOGIN_RATE_LIMIT_LOCK:

        failures = [
            timestamp
            for timestamp in login_failures.get(
                client_key,
                []
            )
            if (
                now
                - timestamp
            ) <= LOGIN_FAILURE_WINDOW_SECONDS
        ]

        failures.append(
            now
        )

        login_failures[
            client_key
        ] = failures


def clear_login_failures(
    client_key
):

    with LOGIN_RATE_LIMIT_LOCK:

        login_failures.pop(
            client_key,
            None
        )


# -------------------------------------------------
# BASIC FUNCTIONS
# -------------------------------------------------

def read_file(path):

    try:
        return Path(path).read_text().strip()

    except Exception:
        return None


def get_size(device_path):

    sectors = read_file(
        device_path / "size"
    )

    if not sectors:
        return 0

    try:
        return int(sectors) * SECTOR_SIZE

    except Exception:
        return 0


def get_partitions(
    device_path,
    device
):

    partitions = []

    try:

        for child in device_path.iterdir():

            name = child.name

            if (
                name.startswith(device)
                and name != device
                and (child / "partition").exists()
            ):

                partitions.append(name)

    except Exception:
        pass

    return sorted(partitions)


def get_devices():

    devices = []

    if not SYS_BLOCK.exists():
        return devices

    try:

        paths = sorted(
            SYS_BLOCK.iterdir(),
            key=lambda x: x.name
        )

    except Exception:
        return devices

    for device_path in paths:

        device = device_path.name

        if device.startswith(
            (
                "loop",
                "ram",
                "dm-",
                "md",
                "zram"
            )
        ):
            continue

        if get_size(device_path) == 0:
            continue

        devices.append(
            (
                device,
                device_path
            )
        )

    return devices


# -------------------------------------------------
# DEVICE TYPE
# -------------------------------------------------

def get_device_transport(
    device,
    device_path
):

    if device.startswith("nvme"):
        return "nvme"

    try:

        resolved_device = (
            device_path
            / "device"
        ).resolve()

        resolved_text = str(
            resolved_device
        ).lower()

        if "/usb" in resolved_text:
            return "usb"

        if "/ata" in resolved_text:
            return "ata"

        if "/nvme" in resolved_text:
            return "nvme"

        if "/mmc" in resolved_text:
            return "mmc"

    except Exception:
        pass

    return "unknown"


def get_disk_type(
    device,
    device_path
):

    if device.startswith("nvme"):
        return "SSD"

    model = (
        read_file(
            device_path / "device/model"
        )
        or ""
    ).strip().lower()

    vendor = (
        read_file(
            device_path / "device/vendor"
        )
        or ""
    ).strip().lower()

    removable = read_file(
        device_path / "removable"
    )

    rotational = read_file(
        device_path / "queue/rotational"
    )

    transport = get_device_transport(
        device,
        device_path
    )

    explicit_flash_markers = (
        "flash",
        "usb stick",
        "thumb drive",
        "pen drive",
        "card reader",
        "sd card",
        "sd/mmc",
        "microsd",
        "massstorageclass"
    )

    if any(
        marker in model
        for marker in explicit_flash_markers
    ):

        return "FLASH"

    # Linux USB bridges sometimes report rotational=1 even for flash
    # media. For removable USB mass-storage devices it is therefore
    # safer to classify conservatively as FLASH than to treat them as
    # mechanical HDDs and later offer HDD-only standby commands.
    if (
        transport == "usb"
        and removable == "1"
    ):

        return "FLASH"

    # Generic by itself is not enough to call a drive flash; many USB
    # bridges use generic vendor strings. Only use it together with a
    # removable non-rotating/unknown USB device.
    if (
        transport == "usb"
        and vendor == "generic"
        and rotational != "1"
    ):

        return "FLASH"

    if transport == "mmc":
        return "FLASH"

    if rotational == "1":
        return "HDD"

    if rotational == "0":
        return "SSD"

    return "UNKNOWN"


# -------------------------------------------------
# MOUNTPOINTS + RAID
# -------------------------------------------------

def normalize_mount_source_names(
    source
):

    names = set()

    if not source.startswith(
        "/dev/"
    ):
        return names

    raw_name = source.replace(
        "/dev/",
        "",
        1
    )

    if raw_name:

        names.add(
            raw_name
        )

        names.add(
            Path(
                raw_name
            ).name
        )

    try:

        resolved = os.path.realpath(
            source
        )

        if resolved.startswith(
            "/dev/"
        ):

            resolved_name = resolved.replace(
                "/dev/",
                "",
                1
            )

            if resolved_name:

                names.add(
                    resolved_name
                )

                names.add(
                    Path(
                        resolved_name
                    ).name
                )

    except Exception:
        pass

    return {
        name
        for name in names
        if name
    }


def get_mounts():

    mounts = {}

    try:

        for line in PROC_MOUNTS.read_text(
            encoding="utf-8",
            errors="replace"
        ).splitlines():

            parts = line.split()

            if len(parts) < 2:
                continue

            source = parts[0]

            # /proc/mounts escapes spaces and a few other characters.
            mountpoint = (
                parts[1]
                .replace(
                    "\\040",
                    " "
                )
                .replace(
                    "\\011",
                    "\t"
                )
                .replace(
                    "\\012",
                    "\n"
                )
                .replace(
                    "\\134",
                    "\\"
                )
            )

            for device in (
                normalize_mount_source_names(
                    source
                )
            ):

                mounts.setdefault(
                    device,
                    []
                ).append(
                    mountpoint
                )

    except Exception:
        pass

    return {
        device: sorted(
            set(
                paths
            )
        )
        for device, paths
        in mounts.items()
    }


def get_disk_mountpoints(
    device_path,
    device,
    mounts
):

    mountpoints = []

    if device in mounts:

        mountpoints.extend(
            mounts[
                device
            ]
        )

    for partition in get_partitions(
        device_path,
        device
    ):

        if partition in mounts:

            mountpoints.extend(
                mounts[
                    partition
                ]
            )

    return sorted(
        set(
            mountpoints
        )
    )


def get_display_mountpoint(
    mountpoints
):

    for mountpoint in mountpoints:

        if mountpoint.startswith(
            "/media/"
        ):
            return mountpoint

    if mountpoints:
        return mountpoints[0]

    return None


def get_physical_name_map():

    physical_map = {}

    for device, device_path in get_devices():

        physical_map[
            device
        ] = device

        for partition in get_partitions(
            device_path,
            device
        ):

            physical_map[
                partition
            ] = device

    return physical_map


def get_raw_raid_members():

    raid_members = {}

    if not SYS_BLOCK.exists():
        return raid_members

    try:

        raid_paths = sorted(
            (
                path
                for path in SYS_BLOCK.iterdir()
                if path.name.startswith(
                    "md"
                )
                and (
                    path / "md"
                ).exists()
            ),
            key=lambda path: path.name
        )

    except Exception:
        return raid_members

    for raid_path in raid_paths:

        slaves_path = (
            raid_path / "slaves"
        )

        try:

            slaves = sorted(
                path.name
                for path in slaves_path.iterdir()
            )

        except Exception:
            slaves = []

        raid_members[
            raid_path.name
        ] = slaves

    return raid_members


def resolve_raid_physical_members(
    name,
    raw_raid_members,
    physical_map,
    seen=None
):

    if seen is None:
        seen = set()

    if name in seen:
        return set()

    seen = set(
        seen
    )

    seen.add(
        name
    )

    if name in physical_map:

        return {
            physical_map[
                name
            ]
        }

    if name in raw_raid_members:

        result = set()

        for child in raw_raid_members[
            name
        ]:

            result.update(
                resolve_raid_physical_members(
                    child,
                    raw_raid_members,
                    physical_map,
                    seen
                )
            )

        return result

    # A partition of an md device can theoretically be used as another
    # stacked block device. Resolve it back to the parent md name.
    for raid_name in raw_raid_members:

        raid_path = (
            SYS_BLOCK / raid_name
        )

        try:

            partitions = get_partitions(
                raid_path,
                raid_name
            )

        except Exception:
            partitions = []

        if name in partitions:

            return resolve_raid_physical_members(
                raid_name,
                raw_raid_members,
                physical_map,
                seen
            )

    return set()


def get_raid_topology(
    mounts=None
):

    if mounts is None:

        mounts = get_mounts()

    physical_map = (
        get_physical_name_map()
    )

    raw_raid_members = (
        get_raw_raid_members()
    )

    topology = {}

    for (
        raid_name,
        raw_members
    ) in raw_raid_members.items():

        raid_path = (
            SYS_BLOCK / raid_name
        )

        physical_members = sorted(
            resolve_raid_physical_members(
                raid_name,
                raw_raid_members,
                physical_map
            )
        )

        raid_mountpoints = (
            get_disk_mountpoints(
                raid_path,
                raid_name,
                mounts
            )
        )

        sync_action = (
            read_file(
                raid_path
                / "md/sync_action"
            )
            or None
        )

        degraded_raw = (
            read_file(
                raid_path
                / "md/degraded"
            )
        )

        try:
            degraded = (
                int(degraded_raw)
                if degraded_raw is not None
                else None
            )
        except Exception:
            degraded = None

        topology[
            raid_name
        ] = {
            "device": raid_name,
            "path": f"/dev/{raid_name}",
            "size_bytes": get_size(
                raid_path
            ),
            "level": (
                read_file(
                    raid_path
                    / "md/level"
                )
                or "raid"
            ),
            "state": (
                read_file(
                    raid_path
                    / "md/array_state"
                )
                or None
            ),
            "sync_action": sync_action,
            "degraded": degraded,
            "raw_members": raw_members,
            "physical_members":
                physical_members,
            "mountpoints":
                raid_mountpoints,
            "display_mountpoint":
                get_display_mountpoint(
                    raid_mountpoints
                )
        }

    return topology


def get_raid_memberships_for_device(
    device,
    raid_topology
):

    memberships = []

    for raid in (
        raid_topology.values()
    ):

        if device not in raid.get(
            "physical_members",
            []
        ):
            continue

        memberships.append(
            {
                "device": raid.get(
                    "device"
                ),
                "path": raid.get(
                    "path"
                ),
                "size_bytes": raid.get(
                    "size_bytes",
                    0
                ),
                "physical_members": raid.get(
                    "physical_members",
                    []
                ),
                "level": raid.get(
                    "level"
                ),
                "state": raid.get(
                    "state"
                ),
                "sync_action": raid.get(
                    "sync_action"
                ),
                "degraded": raid.get(
                    "degraded"
                ),
                "mountpoints": raid.get(
                    "mountpoints",
                    []
                ),
                "display_mountpoint":
                    raid.get(
                        "display_mountpoint"
                    )
            }
        )

    return sorted(
        memberships,
        key=lambda item: (
            item.get(
                "device"
            )
            or ""
        )
    )


def get_effective_mountpoints(
    direct_mountpoints,
    raid_memberships
):

    effective = list(
        direct_mountpoints
    )

    for raid in raid_memberships:

        effective.extend(
            raid.get(
                "mountpoints",
                []
            )
        )

    return sorted(
        set(
            effective
        )
    )


# -------------------------------------------------
# DISK ACTIVITY
# -------------------------------------------------

def read_disk_stats(
    device_path
):

    try:

        values = (
            device_path / "stat"
        ).read_text().split()

        if len(values) < 7:
            return None

        return {
            "reads": int(values[0]),
            "sectors_read": int(values[2]),
            "writes": int(values[4]),
            "sectors_written": int(values[6]),
            "timestamp": time.time()
        }

    except Exception:
        return None


def update_disk_activity(
    device,
    device_path
):

    current = read_disk_stats(
        device_path
    )

    if current is None:
        return

    previous = previous_stats.get(
        device
    )

    if previous is None:

        previous_stats[device] = current

        disk_activity[device] = {
            "status": "IDLE",
            "read_bytes_per_sec": 0,
            "write_bytes_per_sec": 0,
            "read_ops_per_sec": 0,
            "write_ops_per_sec": 0,
            "last_activity": None,
            "idle_since": datetime.now(
                timezone.utc
            ).isoformat()
        }

        save_disk_activity_state(
            force=True
        )

        return

    elapsed = (
        current["timestamp"]
        - previous["timestamp"]
    )

    if elapsed <= 0:
        elapsed = INTERVAL

    read_bytes = (
        current["sectors_read"]
        - previous["sectors_read"]
    ) * SECTOR_SIZE

    write_bytes = (
        current["sectors_written"]
        - previous["sectors_written"]
    ) * SECTOR_SIZE

    read_ops = (
        current["reads"]
        - previous["reads"]
    )

    write_ops = (
        current["writes"]
        - previous["writes"]
    )

    counters_reset = (
        read_bytes < 0
        or write_bytes < 0
        or read_ops < 0
        or write_ops < 0
    )

    if counters_reset:

        previous_stats[
            device
        ] = current

        disk_activity[
            device
        ] = {
            "status": "IDLE",
            "read_bytes_per_sec": 0,
            "write_bytes_per_sec": 0,
            "read_ops_per_sec": 0,
            "write_ops_per_sec": 0,
            "last_activity": None,
            "idle_since": datetime.now(
                timezone.utc
            ).isoformat()
        }

        save_disk_activity_state(
            force=True
        )

        return

    active = (
        read_bytes > 0
        or write_bytes > 0
        or read_ops > 0
        or write_ops > 0
    )

    previous_stats[device] = current

    previous_activity = disk_activity.get(
        device,
        {}
    )

    now_iso = datetime.now(
        timezone.utc
    ).isoformat()

    if active:

        last_activity = now_iso
        idle_since = None

    else:

        last_activity = previous_activity.get(
            "last_activity"
        )

        if previous_activity.get(
            "status"
        ) == "ACTIVE":

            idle_since = now_iso

        else:

            idle_since = (
                previous_activity.get(
                    "idle_since"
                )
                or now_iso
            )

    disk_activity[device] = {

        "status": (
            "ACTIVE"
            if active
            else "IDLE"
        ),

        "read_bytes_per_sec": round(
            max(
                0,
                read_bytes / elapsed
            ),
            2
        ),

        "write_bytes_per_sec": round(
            max(
                0,
                write_bytes / elapsed
            ),
            2
        ),

        "read_ops_per_sec": round(
            max(
                0,
                read_ops / elapsed
            ),
            2
        ),

        "write_ops_per_sec": round(
            max(
                0,
                write_ops / elapsed
            ),
            2
        ),

        "last_activity": last_activity,
        "idle_since": idle_since
    }

    save_disk_activity_state()


# -------------------------------------------------
# CURRENT PROCESS / PATH ACCESS
# -------------------------------------------------

def add_block_device_number_mapping(
    device_number_map,
    block_name,
    physical_devices
):

    try:

        device_stat = os.stat(
            f"/dev/{block_name}"
        )

        if not stat.S_ISBLK(
            device_stat.st_mode
        ):
            return

        device_number = (
            device_stat.st_rdev
        )

        existing = set(
            device_number_map.get(
                device_number,
                []
            )
        )

        existing.update(
            physical_devices
        )

        device_number_map[
            device_number
        ] = sorted(
            existing
        )

    except Exception:
        return


def get_block_device_number_map():

    device_number_map = {}

    # Direct physical disks and their partitions.
    for device, device_path in get_devices():

        names = [
            device
        ]

        names.extend(
            get_partitions(
                device_path,
                device
            )
        )

        for name in names:

            add_block_device_number_mapping(
                device_number_map,
                name,
                [
                    device
                ]
            )

    # Linux software RAID (md). A file opened on the mounted md filesystem
    # has st_dev equal to the md block device. Map that device number back
    # to every physical member so "Current access" is visible on each disk.
    raid_topology = (
        get_raid_topology()
    )

    for raid in raid_topology.values():

        physical_members = (
            raid.get(
                "physical_members",
                []
            )
        )

        if not physical_members:
            continue

        raid_name = raid.get(
            "device"
        )

        if not raid_name:
            continue

        raid_path = (
            SYS_BLOCK / raid_name
        )

        raid_names = [
            raid_name
        ]

        raid_names.extend(
            get_partitions(
                raid_path,
                raid_name
            )
        )

        for name in raid_names:

            add_block_device_number_mapping(
                device_number_map,
                name,
                physical_members
            )

    return device_number_map


def get_mountpoint_physical_device_map():

    """
    Build a longest-prefix mountpoint map for current-access attribution.

    Why this exists:
    ----------------
    ext4 usually exposes a file's st_dev as the actual block-device
    major/minor, so the existing st_dev mapping works well.

    Btrfs can expose an anonymous filesystem device number instead.
    In that case a file on /dev/sdb or /dev/md0 may NOT have st_dev equal
    to the rdev of /dev/sdb or /dev/md0. That caused Current Access to work
    on USB/ext4 disks but fail intermittently or completely on Btrfs and md RAID.

    /proc/1/mountinfo still tells us the mounted source (for example
    /dev/sdb or /dev/md0), so we also map an FD target by its longest matching
    host mountpoint.
    """

    result = {}

    mountinfo_map = (
        get_host_mountinfo_map()
    )

    if not mountinfo_map:
        return result

    physical_map = (
        get_physical_name_map()
    )

    raid_topology = (
        get_raid_topology()
    )

    raid_name_map = {}

    for raid in raid_topology.values():

        raid_name = raid.get(
            "device"
        )

        members = sorted(
            set(
                raid.get(
                    "physical_members",
                    []
                )
            )
        )

        if (
            raid_name
            and members
        ):

            raid_name_map[
                raid_name
            ] = members

            raid_path = (
                SYS_BLOCK
                / raid_name
            )

            for partition in get_partitions(
                raid_path,
                raid_name
            ):

                raid_name_map[
                    partition
                ] = members

    for (
        mountpoint,
        info
    ) in mountinfo_map.items():

        source = str(
            info.get(
                "source",
                ""
            )
            or ""
        )

        if not source.startswith(
            "/dev/"
        ):
            continue

        source_names = (
            normalize_mount_source_names(
                source
            )
        )

        physical_devices = set()

        for source_name in source_names:

            if source_name in physical_map:

                physical_devices.add(
                    physical_map[
                        source_name
                    ]
                )

            if source_name in raid_name_map:

                physical_devices.update(
                    raid_name_map[
                        source_name
                    ]
                )

        if not physical_devices:
            continue

        result[
            mountpoint
        ] = sorted(
            physical_devices
        )

    return result


def get_devices_for_fd_target_path(
    target,
    mountpoint_device_map
):

    if not target:
        return []

    # Linux appends " (deleted)" to some open-but-unlinked FD paths.
    lookup_target = target

    if lookup_target.endswith(
        " (deleted)"
    ):

        lookup_target = lookup_target[
            :-10
        ]

    best_mountpoint = None
    best_devices = []

    for (
        mountpoint,
        devices
    ) in mountpoint_device_map.items():

        if not mountpoint:
            continue

        if mountpoint == "/":

            matches = (
                lookup_target.startswith(
                    "/"
                )
            )

        else:

            matches = (
                lookup_target == mountpoint
                or lookup_target.startswith(
                    mountpoint.rstrip(
                        "/"
                    )
                    + "/"
                )
            )

        if not matches:
            continue

        if (
            best_mountpoint is None
            or len(
                mountpoint
            ) > len(
                best_mountpoint
            )
        ):

            best_mountpoint = mountpoint
            best_devices = list(
                devices
            )

    return sorted(
        set(
            best_devices
        )
    )


def read_process_io(
    pid_path
):

    try:

        text = (
            pid_path / "io"
        ).read_text(
            encoding="utf-8",
            errors="replace"
        )

    except Exception:
        return None

    values = {}

    for line in text.splitlines():

        if ":" not in line:
            continue

        key, value = line.split(
            ":",
            1
        )

        try:
            values[
                key.strip()
            ] = int(
                value.strip()
            )

        except Exception:
            continue

    required = (
        "read_bytes",
        "write_bytes"
    )

    if not all(
        key in values
        for key in required
    ):

        return None

    return values


def read_process_name(
    pid_path
):

    try:

        name = (
            pid_path / "comm"
        ).read_text(
            encoding="utf-8",
            errors="replace"
        ).strip()

        if name:
            return name

    except Exception:
        pass

    return "unknown"


def get_process_fd_targets(
    pid_path,
    device_number_map,
    mountpoint_device_map
):

    targets = {}

    fd_dir = (
        pid_path / "fd"
    )

    try:

        fd_entries = list(
            fd_dir.iterdir()
        )

    except Exception:
        return targets

    for fd_path in fd_entries:

        try:

            target_stat = os.stat(
                fd_path
            )

            if stat.S_ISBLK(
                target_stat.st_mode
            ):

                device_number = (
                    target_stat.st_rdev
                )

            else:

                device_number = (
                    target_stat.st_dev
                )

            target = os.readlink(
                fd_path
            )

            if not target:
                continue

            # Ignore anonymous kernel objects. Normal files, directories
            # and raw /dev paths remain visible.
            if not (
                target.startswith("/")
                or target.startswith("./")
            ):
                continue

            devices = set(
                device_number_map.get(
                    device_number,
                    []
                )
            )

            # Btrfs may use an anonymous st_dev which does not match the
            # actual block device. Resolve the FD path through mountinfo too.
            devices.update(
                get_devices_for_fd_target_path(
                    target,
                    mountpoint_device_map
                )
            )

            if not devices:
                continue

            for device in sorted(
                devices
            ):

                target_list = (
                    targets.setdefault(
                        device,
                        []
                    )
                )

                if (
                    target not in target_list
                    and len(
                        target_list
                    ) < MAX_ACCESS_PATHS_PER_PROCESS
                ):

                    target_list.append(
                        target
                    )

        except Exception:
            continue

    return targets


def update_process_access():

    global process_io_previous
    global current_process_access

    if not HOST_PROC.exists():
        return

    device_number_map = (
        get_block_device_number_map()
    )

    mountpoint_device_map = (
        get_mountpoint_physical_device_map()
    )

    if (
        not device_number_map
        and not mountpoint_device_map
    ):
        return

    now = time.time()

    try:

        pid_paths = [
            path
            for path in HOST_PROC.iterdir()
            if path.name.isdigit()
        ]

    except Exception:
        return

    live_pids = set()

    for pid_path in pid_paths:

        pid = pid_path.name

        io_values = read_process_io(
            pid_path
        )

        if io_values is None:
            continue

        live_pids.add(
            pid
        )

        previous = (
            process_io_previous.get(
                pid
            )
        )

        process_io_previous[
            pid
        ] = {
            "read_bytes": io_values.get(
                "read_bytes",
                0
            ),
            "write_bytes": io_values.get(
                "write_bytes",
                0
            ),
            "time": now
        }

        if not previous:
            continue

        elapsed = max(
            0.001,
            now
            - previous.get(
                "time",
                now
            )
        )

        read_delta = max(
            0,
            io_values.get(
                "read_bytes",
                0
            )
            - previous.get(
                "read_bytes",
                0
            )
        )

        write_delta = max(
            0,
            io_values.get(
                "write_bytes",
                0
            )
            - previous.get(
                "write_bytes",
                0
            )
        )

        if (
            read_delta <= 0
            and write_delta <= 0
        ):
            continue

        fd_targets = (
            get_process_fd_targets(
                pid_path,
                device_number_map,
                mountpoint_device_map
            )
        )

        if not fd_targets:
            continue

        if (
            read_delta > 0
            and write_delta > 0
        ):

            operation = (
                "READ_WRITE"
            )

        elif write_delta > 0:

            operation = (
                "WRITE"
            )

        else:

            operation = (
                "READ"
            )

        process_name = (
            read_process_name(
                pid_path
            )
        )

        for (
            device,
            paths
        ) in fd_targets.items():

            bucket = (
                current_process_access.setdefault(
                    device,
                    {}
                )
            )

            for target in paths:

                key = (
                    f"{pid}\\x00"
                    f"{target}"
                )

                bucket[
                    key
                ] = {
                    "pid": int(
                        pid
                    ),
                    "process": process_name,
                    "path": target,
                    "operation": operation,
                    "read_bytes_per_sec": round(
                        read_delta
                        / elapsed,
                        2
                    ),
                    "write_bytes_per_sec": round(
                        write_delta
                        / elapsed,
                        2
                    ),
                    "last_seen_epoch": now,
                    "last_seen": datetime.now(
                        timezone.utc
                    ).isoformat()
                }

    # Remove PIDs which have disappeared so a later reused PID starts
    # with a fresh baseline.
    dead_pids = (
        set(
            process_io_previous.keys()
        )
        - live_pids
    )

    for pid in dead_pids:

        process_io_previous.pop(
            pid,
            None
        )

    # Remove old access entries. Short events remain visible for a few
    # seconds so they are not missed by the browser refresh interval.
    for device in list(
        current_process_access.keys()
    ):

        bucket = (
            current_process_access[
                device
            ]
        )

        disk_has_recent_io = (
            activity_is_recent(
                disk_activity.get(
                    device,
                    {}
                ),
                PROCESS_ACCESS_DISK_IO_HOLD_SECONDS
            )
        )

        expired = [
            key
            for key, entry
            in bucket.items()
            if (
                (
                    now
                    - entry.get(
                        "last_seen_epoch",
                        0
                    )
                ) > PROCESS_ACCESS_TTL
                and not disk_has_recent_io
            )
        ]

        for key in expired:

            bucket.pop(
                key,
                None
            )

        if not bucket:

            current_process_access.pop(
                device,
                None
            )


def get_current_process_access(
    device
):

    now = time.time()

    bucket = (
        current_process_access.get(
            device,
            {}
        )
    )

    entries = []

    for entry in bucket.values():

        entry_age = (
            now
            - entry.get(
                "last_seen_epoch",
                0
            )
        )

        if (
            entry_age
            > PROCESS_ACCESS_TTL
            and not activity_is_recent(
                disk_activity.get(
                    device,
                    {}
                ),
                PROCESS_ACCESS_DISK_IO_HOLD_SECONDS
            )
        ):
            continue

        item = dict(
            entry
        )

        item.pop(
            "last_seen_epoch",
            None
        )

        entries.append(
            item
        )

    entries.sort(
        key=lambda item: (
            item.get(
                "last_seen",
                ""
            ),
            item.get(
                "process",
                ""
            )
        ),
        reverse=True
    )

    return entries[
        :MAX_ACCESS_ENTRIES_PER_DISK
    ]


# -------------------------------------------------
# DISK MONITOR RESOURCE USAGE
# -------------------------------------------------

def read_text_value(
    path
):

    try:

        return Path(
            path
        ).read_text(
            encoding="utf-8",
            errors="replace"
        ).strip()

    except Exception:
        return None


def read_cgroup_cpu_usage_seconds():

    # cgroup v2
    cpu_stat = (
        CGROUP_ROOT
        / "cpu.stat"
    )

    try:

        if cpu_stat.exists():

            values = {}

            for line in cpu_stat.read_text(
                encoding="utf-8",
                errors="replace"
            ).splitlines():

                parts = line.split()

                if len(parts) == 2:

                    values[
                        parts[0]
                    ] = parts[1]

            if "usage_usec" in values:

                return (
                    int(
                        values[
                            "usage_usec"
                        ]
                    )
                    / 1_000_000.0
                )

    except Exception:
        pass

    # cgroup v1
    candidates = [
        CGROUP_ROOT
        / "cpuacct/cpuacct.usage",
        CGROUP_ROOT
        / "cpu,cpuacct/cpuacct.usage"
    ]

    for path in candidates:

        try:

            if path.exists():

                return (
                    int(
                        path.read_text().strip()
                    )
                    / 1_000_000_000.0
                )

        except Exception:
            continue

    return None


def read_cgroup_memory():

    memory_bytes = None
    memory_limit_bytes = None

    # cgroup v2
    try:

        current_path = (
            CGROUP_ROOT
            / "memory.current"
        )

        if current_path.exists():

            memory_bytes = int(
                current_path.read_text().strip()
            )

            max_value = read_text_value(
                CGROUP_ROOT
                / "memory.max"
            )

            if (
                max_value
                and max_value != "max"
            ):

                memory_limit_bytes = int(
                    max_value
                )

            return (
                memory_bytes,
                memory_limit_bytes
            )

    except Exception:
        pass

    # cgroup v1
    try:

        usage_candidates = [
            CGROUP_ROOT
            / "memory/memory.usage_in_bytes"
        ]

        limit_candidates = [
            CGROUP_ROOT
            / "memory/memory.limit_in_bytes"
        ]

        for path in usage_candidates:

            if path.exists():

                memory_bytes = int(
                    path.read_text().strip()
                )

                break

        for path in limit_candidates:

            if path.exists():

                value = int(
                    path.read_text().strip()
                )

                # Very large values are the usual v1 representation
                # of "unlimited".
                if value < (
                    1 << 60
                ):

                    memory_limit_bytes = value

                break

    except Exception:
        pass

    return (
        memory_bytes,
        memory_limit_bytes
    )


def update_resource_usage():

    global resource_usage
    global resource_cpu_previous

    now = time.time()

    cpu_usage_seconds = (
        read_cgroup_cpu_usage_seconds()
    )

    cpu_percent = (
        resource_usage.get(
            "cpu_percent",
            0.0
        )
        or 0.0
    )

    previous_usage = (
        resource_cpu_previous.get(
            "usage_seconds"
        )
    )

    previous_time = (
        resource_cpu_previous.get(
            "time"
        )
    )

    if (
        cpu_usage_seconds is not None
        and previous_usage is not None
        and previous_time is not None
    ):

        elapsed = max(
            0.001,
            now - previous_time
        )

        cpu_delta = max(
            0.0,
            cpu_usage_seconds
            - previous_usage
        )

        # Same convention as Docker's CPU percentage:
        # 100% means roughly one full CPU core.
        cpu_percent = (
            cpu_delta
            / elapsed
            * 100.0
        )

    if cpu_usage_seconds is not None:

        resource_cpu_previous = {
            "usage_seconds":
                cpu_usage_seconds,
            "time": now
        }

    (
        memory_bytes,
        memory_limit_bytes
    ) = read_cgroup_memory()

    resource_usage = {
        "cpu_percent": round(
            max(
                0.0,
                cpu_percent
            ),
            2
        ),
        "memory_bytes":
            memory_bytes,
        "memory_limit_bytes":
            memory_limit_bytes,
        "updated_at": datetime.now(
            timezone.utc
        ).isoformat()
    }


def get_resource_usage():

    return dict(
        resource_usage
    )


def get_service_runtime():

    return {
        "started_at": APP_STARTED_AT,
        "uptime_seconds": int(
            max(
                0.0,
                time.monotonic()
                - APP_STARTED_MONOTONIC
            )
        )
    }


async def monitor_disks():

    while True:

        current_devices = set()

        for device, device_path in get_devices():

            current_devices.add(
                device
            )

            update_disk_activity(
                device,
                device_path
            )

        # /host/proc is inspected only after the disk counters have
        # been sampled. This never opens the files on the monitored disks.
        update_process_access()

        update_resource_usage()

        now = time.time()

        expired_awake = [
            device
            for device, awake_until
            in manual_awake_until.items()
            if now >= awake_until
        ]

        for device in expired_awake:

            manual_awake_until.pop(
                device,
                None
            )

        removed = (
            set(disk_activity.keys())
            - current_devices
        )

        for device in removed:

            disk_activity.pop(
                device,
                None
            )

            previous_stats.pop(
                device,
                None
            )

            current_process_access.pop(
                device,
                None
            )

            power_smartctl_type_cache.pop(
                device,
                None
            )

            usb_runtime_power_state.pop(
                device,
                None
            )


        await asyncio.sleep(
            INTERVAL
        )


@app.on_event("startup")
async def startup_event():

    load_smart_cache()

    init_smart_history_db()

    seed_smart_history_from_cache()

    load_usb_power_config()

    load_disk_activity_state()

    load_storage_usage_cache()

    load_smart_full_check_state()

    load_smart_automation_config()

    update_resource_usage()

    asyncio.create_task(
        monitor_disks()
    )

    asyncio.create_task(
        monitor_safe_smart_history()
    )


    asyncio.create_task(
        run_startup_smart_check()
    )

    asyncio.create_task(
        monitor_smart_automation()
    )


# -------------------------------------------------
# ZIMAOS STANDBY API
# -------------------------------------------------

def http_get_json(
    url,
    params=None,
    timeout=1.5
):

    if params:

        query = urlencode(
            params
        )

        separator = (
            "&"
            if "?" in url
            else "?"
        )

        url = (
            f"{url}{separator}{query}"
        )

    try:

        request = UrlRequest(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "Disk-Monitor/0.22.9"
            }
        )

        with urlopen(
            request,
            timeout=timeout
        ) as response:

            payload = response.read(
                256 * 1024
            )

        return json.loads(
            payload.decode(
                "utf-8",
                errors="replace"
            )
        )

    except Exception:
        return None


def http_put_json(
    url,
    payload,
    timeout=2.5
):

    try:

        body = json.dumps(
            payload
        ).encode(
            "utf-8"
        )

        request = UrlRequest(
            url,
            data=body,
            method="PUT",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Disk-Monitor/0.22.9"
            }
        )

        with urlopen(
            request,
            timeout=timeout
        ) as response:

            status = int(
                getattr(
                    response,
                    "status",
                    200
                )
            )

            raw = response.read(
                256 * 1024
            )

        data = None

        if raw:

            try:

                data = json.loads(
                    raw.decode(
                        "utf-8",
                        errors="replace"
                    )
                )

            except Exception:
                data = None

        return {
            "ok": (
                200 <= status < 300
            ),
            "status": status,
            "data": data
        }

    except Exception:

        return {
            "ok": False,
            "status": None,
            "data": None
        }


def discover_zimaos_local_storage(
    force=False
):

    global zimaos_local_storage_base_url
    global zimaos_route_last_refresh

    now = time.time()

    if (
        not force
        and zimaos_local_storage_base_url
        and (
            now
            - zimaos_route_last_refresh
        ) < ZIMAOS_ROUTE_CACHE_SECONDS
    ):

        return zimaos_local_storage_base_url

    for routes_url in ZIMAOS_GATEWAY_ROUTES_URLS:

        routes = http_get_json(
            routes_url,
            timeout=1.0
        )

        if not isinstance(
            routes,
            list
        ):
            continue

        for route in routes:

            if not isinstance(
                route,
                dict
            ):
                continue

            if route.get(
                "path"
            ) != "/v2/local_storage":
                continue

            target = route.get(
                "target"
            )

            if not isinstance(
                target,
                str
            ):
                continue

            target = target.rstrip(
                "/"
            )

            if not target:
                continue

            zimaos_local_storage_base_url = (
                f"{target}/v2/local_storage"
            )

            zimaos_route_last_refresh = now

            return (
                zimaos_local_storage_base_url
            )

    # Known ZimaOS default. This also lets the integration work
    # if the gateway route listing is temporarily unavailable.
    zimaos_local_storage_base_url = (
        ZIMAOS_LOCAL_STORAGE_FALLBACK
    )

    zimaos_route_last_refresh = now

    return zimaos_local_storage_base_url


def get_zimaos_standby(
    device
):

    device_path = f"/dev/{device}"

    for attempt in range(2):

        base_url = discover_zimaos_local_storage(
            force=(
                attempt == 1
            )
        )

        if not base_url:
            continue

        data = http_get_json(
            (
                f"{base_url}"
                "/disk/sleep/status"
            ),
            params={
                "device_path": device_path
            },
            timeout=1.5
        )

        if not isinstance(
            data,
            dict
        ):
            continue

        standby = data.get(
            "standby"
        )

        if isinstance(
            standby,
            bool
        ):

            return {
                "available": True,
                "standby": standby,
                "method": "zimaos-local-storage"
            }

    return {
        "available": False,
        "standby": None,
        "method": None
    }


def decode_hdparm_standby_level(
    level
):

    try:
        level = int(
            level
        )

    except Exception:

        return {
            "level": None,
            "enabled": None,
            "seconds": None,
            "kind": "invalid"
        }

    if level == 0:

        return {
            "level": 0,
            "enabled": False,
            "seconds": None,
            "kind": "disabled"
        }

    if 1 <= level <= 240:

        return {
            "level": level,
            "enabled": True,
            "seconds": level * 5,
            "kind": "fixed"
        }

    if 241 <= level <= 251:

        return {
            "level": level,
            "enabled": True,
            "seconds": (
                level - 240
            ) * 30 * 60,
            "kind": "fixed"
        }

    # ATA/hdparm special timer codes.
    if level == 252:

        return {
            "level": level,
            "enabled": True,
            "seconds": 21 * 60,
            "kind": "fixed"
        }

    if level == 253:

        return {
            "level": level,
            "enabled": True,
            "seconds": None,
            "kind": "vendor"
        }

    if level == 254:

        return {
            "level": level,
            "enabled": True,
            "seconds": None,
            "kind": "reserved"
        }

    if level == 255:

        return {
            "level": level,
            "enabled": True,
            "seconds": (
                21 * 60
                + 15
            ),
            "kind": "fixed"
        }

    return {
        "level": level,
        "enabled": None,
        "seconds": None,
        "kind": "invalid"
    }


def get_zimaos_standby_timer():

    for attempt in range(2):

        base_url = discover_zimaos_local_storage(
            force=(
                attempt == 1
            )
        )

        if not base_url:
            continue

        data = http_get_json(
            (
                f"{base_url}"
                "/disk/sleep"
            ),
            timeout=1.5
        )

        if not isinstance(
            data,
            dict
        ):
            continue

        level = data.get(
            "level"
        )

        decoded = decode_hdparm_standby_level(
            level
        )

        if decoded.get(
            "level"
        ) is not None:

            return {
                "available": True,
                "source": "zimaos-local-storage",
                **decoded
            }

    return {
        "available": False,
        "source": None,
        "level": None,
        "enabled": None,
        "seconds": None,
        "kind": "unavailable"
    }


def set_zimaos_standby_timer(
    level
):

    try:

        level = int(
            level
        )

    except Exception:

        return {
            "success": False,
            "verified": False,
            "reason": "invalid_level",
            "requested_level": None,
            "readback_level": None,
            "put_status": None,
            "timer": None
        }

    if (
        level
        not in ZIMAOS_STANDBY_ALLOWED_LEVELS
    ):

        return {
            "success": False,
            "verified": False,
            "reason": "invalid_level",
            "requested_level": level,
            "readback_level": None,
            "put_status": None,
            "timer": None
        }

    last_put_status = None
    last_put_data = None
    last_timer = None

    for attempt in range(2):

        base_url = discover_zimaos_local_storage(
            force=(
                attempt == 1
            )
        )

        if not base_url:
            continue

        result = http_put_json(
            (
                f"{base_url}"
                "/disk/sleep"
            ),
            {
                "level": level
            },
            timeout=2.5
        )

        last_put_status = result.get(
            "status"
        )
        last_put_data = result.get(
            "data"
        )

        if not result.get(
            "ok"
        ):
            continue

        # IMPORTANT: Never report the requested timer as the real state.
        # ZimaOS may acknowledge a PUT before its persisted setting is visible,
        # so verify the value by reading /disk/sleep back several times.
        for verify_delay in (
            0.0,
            0.20,
            0.50,
            1.00
        ):

            if verify_delay > 0:
                time.sleep(
                    verify_delay
                )

            timer = get_zimaos_standby_timer()
            last_timer = timer

            readback_level = timer.get(
                "level"
            )

            try:
                readback_level = int(
                    readback_level
                )
            except Exception:
                readback_level = None

            if (
                timer.get(
                    "available"
                )
                and readback_level == level
            ):

                return {
                    "success": True,
                    "verified": True,
                    "reason": None,
                    "requested_level": level,
                    "readback_level": readback_level,
                    "put_status": last_put_status,
                    "put_data": last_put_data,
                    "timer": timer
                }

        # A 2xx PUT is not enough. If read-back still differs, treat this as
        # a real failure instead of making the dashboard pretend it changed.
        readback_level = None

        if isinstance(
            last_timer,
            dict
        ):
            try:
                readback_level = int(
                    last_timer.get(
                        "level"
                    )
                )
            except Exception:
                readback_level = None

        return {
            "success": False,
            "verified": False,
            "reason": "verification_failed",
            "requested_level": level,
            "readback_level": readback_level,
            "put_status": last_put_status,
            "put_data": last_put_data,
            "timer": last_timer
        }

    return {
        "success": False,
        "verified": False,
        "reason": "zimaos_write_failed",
        "requested_level": level,
        "readback_level": (
            last_timer.get(
                "level"
            )
            if isinstance(
                last_timer,
                dict
            )
            else None
        ),
        "put_status": last_put_status,
        "put_data": last_put_data,
        "timer": last_timer
    }


# -------------------------------------------------
# COMMANDS
# -------------------------------------------------

def run_command(
    command,
    timeout=15
):

    try:

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        output = (
            result.stdout
            + "\n"
            + result.stderr
        )

        return {
            "returncode": result.returncode,
            "output": output,
            "output_lower": output.lower()
        }

    except Exception as error:

        return {
            "returncode": -1,
            "output": str(error),
            "output_lower": str(error).lower()
        }


def smartctl_score(
    output
):

    text = (
        output
        or ""
    ).lower()

    score = 0

    markers = [
        "smart overall-health",
        "smart health status",
        "smart attributes data structure",
        "vendor specific smart attributes",
        "temperature_celsius",
        "current drive temperature",
        "power_on_hours",
        "power on hours",
        "critical warning",
        "percentage used",
        "media and data integrity errors"
    ]

    for marker in markers:

        if marker in text:
            score += 10

    ata_attribute_rows = re.findall(
        r"^\s*\d+\s+[A-Za-z0-9_\-]+\s+0x[0-9a-fA-F]+\s+\d+\s+\d+\s+\d+\s+",
        output or "",
        re.MULTILINE
    )
    score += min(len(ata_attribute_rows) * 2, 80)

    if "device model:" in text:
        score += 2

    if "model number:" in text:
        score += 2

    if "serial number:" in text:
        score += 2

    negative_markers = [
        "unknown usb bridge",
        "please specify device type",
        "scsi error unsupported field",
        "scsi error unsupported scsi opcode",
        "read device identity failed",
        "a mandatory smart command failed",
        "smartctl open device",
        "failed: invalid argument"
    ]

    for marker in negative_markers:

        if marker in text:
            score -= 20

    return score


def run_smartctl_best(
    device,
    options,
    timeout=30,
    stop_on_standby=True
):

    device_path = f"/dev/{device}"

    variants = [
        None,
        "sat",
        "sat,12",
        "sat,16",
        "scsi"
    ]

    device_sys_path = (
        SYS_BLOCK / device
    )

    is_usb = (
        get_device_transport(
            device,
            device_sys_path
        )
        == "usb"
    )

    best = None
    best_device_type = None
    best_score = -10_000

    for device_type in variants:

        command = [
            "smartctl"
        ]

        command.extend(
            options
        )

        if device_type:

            command.extend(
                [
                    "-d",
                    device_type
                ]
            )

        command.append(
            device_path
        )

        result = run_command(
            command,
            timeout=timeout
        )

        score = smartctl_score(
            result["output"]
        )

        # A successful explicit standby result is immediately useful,
        # even if it contains little SMART payload.
        lowered = result[
            "output_lower"
        ]

        if (
            stop_on_standby
            and (
                "device is in standby mode"
                in lowered
                or "device is in sleeping mode"
                in lowered
            )
        ):

            return result, device_type

        if score > best_score:

            best = result
            best_device_type = device_type
            best_score = score

            # Native ATA/NVMe usually has one obvious mode and can stop
            # early. USB bridges are different: AUTO/SCSI may return a small
            # amount of information while SAT exposes the full ATA table.
            # Therefore USB evaluates all candidates and keeps the richest
            # successful result.
            if (
                score >= 20
                and not is_usb
            ):
                break

    if best is None:

        best = {
            "returncode": -1,
            "output": "",
            "output_lower": ""
        }

    return best, best_device_type


# -------------------------------------------------
# POWER STATE
# -------------------------------------------------

def activity_is_recent(
    activity,
    max_age_seconds
):

    if not isinstance(
        activity,
        dict
    ):

        return False

    if activity.get(
        "status"
    ) == "ACTIVE":

        return True

    last_activity = activity.get(
        "last_activity"
    )

    if not last_activity:
        return False

    try:

        timestamp = datetime.fromisoformat(
            last_activity
        )

        if timestamp.tzinfo is None:

            timestamp = timestamp.replace(
                tzinfo=timezone.utc
            )

        age_seconds = (
            datetime.now(
                timezone.utc
            )
            - timestamp.astimezone(
                timezone.utc
            )
        ).total_seconds()

        return (
            0
            <= age_seconds
            <= max_age_seconds
        )

    except Exception:
        return False


def set_usb_runtime_power_state(
    device,
    status,
    method,
    device_type=None
):

    if status not in (
        "ACTIVE",
        "STANDBY"
    ):
        return

    usb_runtime_power_state[
        device
    ] = {
        "status": status,
        "method": method,
        "device_type":
            device_type,
        "updated_at_monotonic":
            time.monotonic()
    }


def get_usb_runtime_power_state(
    device
):

    state = usb_runtime_power_state.get(
        device
    )

    if not isinstance(
        state,
        dict
    ):
        return None

    if state.get(
        "status"
    ) not in (
        "ACTIVE",
        "STANDBY"
    ):
        return None

    return dict(
        state
    )


def clear_usb_runtime_power_state(
    device
):

    usb_runtime_power_state.pop(
        device,
        None
    )


def probe_smartctl_power_state_once(
    device,
    preferred_device_type=None
):

    # This function is used only for:
    # - the single initial probe after service start
    # - explicit manual actions that call it directly elsewhere.
    # It is never called by a periodic timer.

    candidates = []

    # AUTO first: this exact mode was proven manually on the tested
    # WD USB HDDs.
    candidates.append(
        None
    )

    if preferred_device_type is not None:

        candidates.append(
            preferred_device_type
        )

    cached_power_type = (
        power_smartctl_type_cache.get(
            device
        )
    )

    if cached_power_type is not None:

        candidates.append(
            None
            if cached_power_type
            == "__auto__"
            else cached_power_type
        )

    cached_smart_type = (
        smart_cache.get(
            device,
            {}
        ).get(
            "smartctl_device_type"
        )
    )

    if cached_smart_type:

        candidates.append(
            cached_smart_type
        )

    candidates.extend(
        [
            "sat",
            "sat,12",
            "sat,16",
            "scsi"
        ]
    )

    checked = []

    for device_type in candidates:

        if device_type in checked:
            continue

        checked.append(
            device_type
        )

        command = [
            "smartctl",
            "-n",
            "standby",
            "-i"
        ]

        if device_type:

            command.extend(
                [
                    "-d",
                    device_type
                ]
            )

        command.append(
            f"/dev/{device}"
        )

        result = run_command(
            command,
            timeout=10
        )

        output = result.get(
            "output_lower",
            ""
        )

        status = None

        if (
            "device is in standby mode"
            in output
            or "device is in sleeping mode"
            in output
            or "power mode is: standby"
            in output
            or "power mode: standby"
            in output
        ):

            status = "STANDBY"

        elif (
            "power mode is: active or idle"
            in output
            or "device is active or idle"
            in output
            or "power mode is: active/idle"
            in output
            or "power mode is: active"
            in output
            or "power mode is: idle"
            in output
        ):

            status = "ACTIVE"

        if status is None:
            continue

        power_smartctl_type_cache[
            device
        ] = (
            device_type
            if device_type
            else "__auto__"
        )

        method = (
            "smartctl"
            if not device_type
            else (
                "smartctl:"
                + device_type
            )
        )

        set_usb_runtime_power_state(
            device,
            status,
            method,
            device_type=device_type
        )

        return {
            "available": True,
            "status": status,
            "device_type":
                device_type,
            "method": method
        }

    return {
        "available": False,
        "status": None,
        "device_type": None,
        "method": "smartctl-unresolved"
    }


def get_smartctl_power_state(
    device,
    preferred_device_type=None,
    force=False
):

    # Compatibility wrapper for explicit/manual code paths.
    # Normal USB dashboard rendering does NOT call this function anymore.
    if not force:

        runtime_state = get_usb_runtime_power_state(
            device
        )

        if runtime_state is not None:

            return {
                "available": True,
                "status":
                    runtime_state.get(
                        "status"
                    ),
                "device_type":
                    runtime_state.get(
                        "device_type"
                    ),
                "method":
                    runtime_state.get(
                        "method"
                    )
            }

    return probe_smartctl_power_state_once(
        device,
        preferred_device_type=
            preferred_device_type
    )


def check_power_state(
    device,
    disk_type,
    activity,
    transport=None,
    usb_standby_minutes=None
):

    last_checked = datetime.now(
        timezone.utc
    ).isoformat()

    if disk_type in (
        "SSD",
        "FLASH"
    ):

        activity_status = activity.get(
            "status"
        )

        return {
            "status": (
                activity_status
                if activity_status in (
                    "ACTIVE",
                    "IDLE"
                )
                else "IDLE"
            ),
            "method": "io",
            "confidence": "confirmed",
            "last_checked": last_checked
        }

    if transport is None:

        device_sys_path = (
            SYS_BLOCK
            / device
        )

        transport = get_device_transport(
            device,
            device_sys_path
        )

    # A successful manual SMART read proves that the drive was reachable.
    # Give that explicit user action priority over a stale ZimaOS standby
    # report or passive USB standby estimate for a short hold window.
    awake_until = manual_awake_until.get(
        device,
        0
    )

    if (
        disk_type == "HDD"
        and time.time() < awake_until
    ):

        return {
            "status": "ACTIVE",
            "method": "manual-smart-confirmed",
            "confidence": "confirmed",
            "last_checked": last_checked
        }

    # -------------------------------------------------
    # USB HDD: fully passive during normal monitoring.
    # -------------------------------------------------
    if (
        disk_type in (
            "HDD",
            "UNKNOWN"
        )
        and transport == "usb"
    ):

        idle_seconds = (
            get_activity_idle_seconds(
                activity
            )
        )

        has_live_io = (
            activity.get(
                "status"
            ) == "ACTIVE"
        )

        has_process_access = bool(
            get_current_process_access(
                device
            )
        )

        if (
            has_live_io
            or has_process_access
            or activity_is_recent(
                activity,
                USB_HDD_ACTIVE_HOLD_SECONDS
            )
        ):

            set_usb_runtime_power_state(
                device,
                "ACTIVE",
                "usb-live-io"
            )

            return {
                "status": "ACTIVE",
                "method": "usb-live-io",
                "confidence": "confirmed",
                "idle_seconds": 0,
                "standby_timer_minutes":
                    usb_standby_minutes,
                "standby_eta_seconds":
                    (
                        usb_standby_minutes * 60
                        if usb_standby_minutes
                        else None
                    ),
                "last_checked":
                    last_checked
            }

        runtime_state = (
            get_usb_runtime_power_state(
                device
            )
        )

        if (
            runtime_state is not None
            and runtime_state.get(
                "status"
            ) == "STANDBY"
        ):

            return {
                "status": "STANDBY",
                "method":
                    runtime_state.get(
                        "method"
                    ),
                "confidence": "confirmed",
                "idle_seconds":
                    round(
                        idle_seconds,
                        1
                    ),
                "standby_timer_minutes":
                    usb_standby_minutes,
                "standby_eta_seconds": 0,
                "last_checked":
                    last_checked
            }

        standby_eta_seconds = None

        if usb_standby_minutes:

            standby_eta_seconds = max(
                0,
                int(
                    usb_standby_minutes
                    * 60
                    - idle_seconds
                )
            )

            if (
                idle_seconds
                >= usb_standby_minutes
                * 60
            ):

                return {
                    "status":
                        "STANDBY_ESTIMATED",
                    "method":
                        "usb-passive-timer",
                    "confidence":
                        "estimated",
                    "idle_seconds":
                        round(
                            idle_seconds,
                            1
                        ),
                    "standby_timer_minutes":
                        usb_standby_minutes,
                    "standby_eta_seconds":
                        0,
                    "last_checked":
                        last_checked
                }

        return {
            "status": "STANDBY_WAITING",
            "method": "usb-passive-timer-waiting",
            "confidence": "estimated",
            "idle_seconds":
                round(
                    idle_seconds,
                    1
                ),
            "standby_timer_minutes":
                usb_standby_minutes,
            "standby_eta_seconds":
                standby_eta_seconds,
            "last_checked":
                last_checked
        }

    # -------------------------------------------------
    # Direct SATA/SAS HDD / non-USB unknown device.
    # -------------------------------------------------

    if disk_type in (
        "HDD",
        "UNKNOWN"
    ):

        zimaos_state = get_zimaos_standby(
            device
        )

        if zimaos_state.get(
            "available"
        ):

            return {
                "status": (
                    "STANDBY"
                    if zimaos_state.get(
                        "standby"
                    )
                    else "ACTIVE"
                ),
                "method":
                    zimaos_state.get(
                        "method"
                    ),
                "confidence": "confirmed",
                "last_checked":
                    last_checked
            }

    if activity.get(
        "status"
    ) == "ACTIVE":

        return {
            "status": "ACTIVE",
            "method": "io-fallback",
            "confidence": "confirmed",
            "last_checked": last_checked
        }

    if not ALLOW_AUTOMATIC_HDD_POWER_PROBES:

        return {
            "status": (
                "ACTIVE"
                if activity.get(
                    "status"
                ) == "ACTIVE"
                else "INACTIVE"
            ),
            "method":
                "passive-no-power-probe",
            "confidence":
                "observed",
            "last_checked":
                last_checked
        }

    result = run_command(
        [
            "hdparm",
            "-C",
            f"/dev/{device}"
        ]
    )

    output = result.get(
        "output_lower",
        ""
    )

    if (
        "drive state is: standby"
        in output
        or "drive state is: sleeping"
        in output
    ):

        return {
            "status": "STANDBY",
            "method": "hdparm-fallback",
            "confidence": "confirmed",
            "last_checked": last_checked
        }

    if (
        "drive state is: active/idle"
        in output
    ):

        return {
            "status": "ACTIVE",
            "method": "hdparm-fallback",
            "confidence": "confirmed",
            "last_checked": last_checked
        }

    smart_power = get_smartctl_power_state(
        device
    )

    if smart_power.get(
        "available"
    ):

        return {
            "status":
                smart_power.get(
                    "status"
                ),
            "method":
                smart_power.get(
                    "method"
                ),
            "confidence": "confirmed",
            "last_checked":
                last_checked
        }

    return {
        "status": "UNKNOWN_IDLE",
        "method": "fallback-unresolved",
        "confidence": "unknown",
        "last_checked": last_checked
    }


# -------------------------------------------------
# EXPLICIT HDD WAKE FOR MANUAL SMART
# -------------------------------------------------

def wake_disk_for_smart(
    device
):

    device_path = f"/dev/{device}"

    device_sys_path = (
        SYS_BLOCK
        / device
    )

    transport = get_device_transport(
        device,
        device_sys_path
    )

    if transport == "usb":

        before = get_smartctl_power_state(
            device,
            force=True
        )

        if (
            before.get(
                "available"
            )
            and before.get(
                "status"
            ) == "ACTIVE"
        ):

            return {
                "success": True,
                "already_awake": True,
                "method": "smartctl-power-state",
                "standby_before": False,
                "standby_after": False
            }

    else:

        before = get_zimaos_standby(
            device
        )

        if (
            before.get(
                "available"
            )
            and before.get(
                "standby"
            ) is False
        ):

            return {
                "success": True,
                "already_awake": True,
                "method": "zimaos-state",
                "standby_before": False,
                "standby_after": False
            }

    wake_commands = [
        [
            "dd",
            f"if={device_path}",
            "of=/dev/null",
            "bs=4096",
            "count=1",
            "iflag=direct",
            "status=none"
        ],
        [
            "dd",
            f"if={device_path}",
            "of=/dev/null",
            "bs=512",
            "count=1",
            "status=none"
        ]
    ]

    wake_result = None

    for command in wake_commands:

        wake_result = run_command(
            command,
            timeout=30
        )

        if wake_result.get(
            "returncode"
        ) == 0:
            break

    if transport == "usb":

        clear_usb_runtime_power_state(
            device
        )

    deadline = time.time() + 20.0
    after = None

    while time.time() < deadline:

        if transport == "usb":

            after = get_smartctl_power_state(
                device,
                force=True
            )

            if (
                after.get(
                    "available"
                )
                and after.get(
                    "status"
                ) == "ACTIVE"
            ):
                break

        else:

            after = get_zimaos_standby(
                device
            )

            if (
                after.get(
                    "available"
                )
                and after.get(
                    "standby"
                ) is False
            ):
                break

        time.sleep(
            0.5
        )

    if transport == "usb":

        success = (
            after is not None
            and after.get(
                "available"
            )
            and after.get(
                "status"
            ) == "ACTIVE"
        )

        if success:

            set_usb_runtime_power_state(
                device,
                "ACTIVE",
                "manual-smart-wake"
            )

        standby_before = (
            True
            if (
                isinstance(
                    before,
                    dict
                )
                and before.get(
                    "status"
                ) == "STANDBY"
            )
            else False
            if (
                isinstance(
                    before,
                    dict
                )
                and before.get(
                    "status"
                ) == "ACTIVE"
            )
            else None
        )

        standby_after = (
            True
            if (
                isinstance(
                    after,
                    dict
                )
                and after.get(
                    "status"
                ) == "STANDBY"
            )
            else False
            if (
                isinstance(
                    after,
                    dict
                )
                and after.get(
                    "status"
                ) == "ACTIVE"
            )
            else None
        )

    else:

        success = (
            after is not None
            and after.get(
                "available"
            )
            and after.get(
                "standby"
            ) is False
        )

        standby_before = (
            before.get(
                "standby"
            )
            if isinstance(
                before,
                dict
            )
            else None
        )

        standby_after = (
            after.get(
                "standby"
            )
            if isinstance(
                after,
                dict
            )
            else None
        )

    return {
        "success": success,
        "already_awake": False,
        "method": "read-only-dd",
        "standby_before":
            standby_before,
        "standby_after":
            standby_after,
        "wake_returncode": (
            wake_result.get(
                "returncode"
            )
            if wake_result
            else None
        )
    }


# -------------------------------------------------
# SMART HELPERS
# -------------------------------------------------

def extract_smart_attribute(
    output,
    attribute_name
):

    pattern = (
        r"^\s*\d+\s+"
        + re.escape(attribute_name)
        + r"\s+.*?(\d+)\s*$"
    )

    match = re.search(
        pattern,
        output,
        re.MULTILINE
    )

    if match:

        try:
            return int(
                match.group(1)
            )

        except Exception:
            return None

    return None


def extract_ata_smart_attributes(
    output
):
    attributes = []
    if not output:
        return attributes

    pattern = re.compile(
        r"^\s*(\d+)\s+([A-Za-z0-9_\-]+)\s+(0x[0-9A-Fa-f]+)\s+"
        r"(\d+)\s+(\d+)\s+(\d+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(.+?)\s*$"
    )

    for line in output.splitlines():
        match = pattern.match(line)
        if not match:
            continue

        def to_int(group):
            try:
                return int(match.group(group))
            except Exception:
                return None

        when_failed = match.group(9)
        attributes.append({
            "id": to_int(1),
            "name": match.group(2),
            "flag": match.group(3),
            "value": to_int(4),
            "worst": to_int(5),
            "threshold": to_int(6),
            "type": match.group(7),
            "updated": match.group(8),
            "when_failed": when_failed,
            "raw": match.group(10).strip(),
            "status": "FAILED" if when_failed and when_failed != "-" else "OK"
        })

    return attributes


def extract_temperature(
    output
):

    # Common smartctl text formats:
    # ATA SMART attribute table, SCT temperature, SCSI/USB bridges,
    # and NVMe text output.
    patterns = [
        r"^\s*\d+\s+Temperature_Celsius\s+.*?\s+(\d+)(?:\s+\([^)]*\))?\s*$",
        r"^\s*\d+\s+Temperature_Internal\s+.*?\s+(\d+)(?:\s+\([^)]*\))?\s*$",
        r"^\s*\d+\s+Airflow_Temperature_Cel\s+.*?\s+(\d+)(?:\s+\([^)]*\))?\s*$",
        r"Current Drive Temperature:\s*(\d+)\s*(?:C|Celsius)?",
        r"Current Temperature:\s*(\d+)\s*(?:C|Celsius)?",
        r"Temperature:\s*(\d+)\s*(?:C|Celsius|°C)?",
        r"Temperature Sensor \d+:\s*(\d+)\s*(?:C|Celsius|°C)?"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            output,
            re.IGNORECASE
            | re.MULTILINE
        )

        if match:

            try:

                value = int(
                    match.group(1)
                )

                if 0 < value < 120:
                    return value

            except Exception:
                pass

    # Last-resort ATA attribute parser: take RAW_VALUE, not normalized VALUE.
    for line in output.splitlines():

        lowered = line.lower()

        if (
            "temperature_celsius"
            not in lowered
            and "temperature_internal"
            not in lowered
            and "airflow_temperature_cel"
            not in lowered
        ):
            continue

        parts = line.split()

        if len(parts) < 2:
            continue

        for token in reversed(parts):

            token = token.strip(
                "(),"
            )

            if not token.isdigit():
                continue

            value = int(
                token
            )

            if 0 < value < 120:
                return value

    return None


def extract_rotation_rate_rpm(
    output
):

    if not output:
        return None

    match = re.search(
        r"^\s*Rotation Rate:\s*([\d,]+)\s*rpm\s*$",
        output,
        re.IGNORECASE
        | re.MULTILINE
    )

    if not match:
        return None

    try:
        return int(
            match.group(1).replace(
                ",",
                ""
            )
        )
    except Exception:
        return None


def extract_power_on_hours(
    output
):

    patterns = [

        r"Power_On_Hours.*?(\d+)\s*$",

        r"Power on Hours:\s*(\d+)",

        r"Power_On_Hours:\s*(\d+)",

        # Common smartctl SCSI/USB bridge format:
        # "Accumulated power on time, hours:minutes 12345:34"
        r"Accumulated power on time,\s*hours:minutes\s*(\d+):\d+"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            output,
            re.MULTILINE
        )

        if match:

            try:
                return int(
                    match.group(1)
                )

            except Exception:
                pass

    return None


def extract_info_value(
    output,
    label
):

    match = re.search(
        rf"^\s*{re.escape(label)}:\s*(.+?)\s*$",
        output,
        re.MULTILINE
    )

    if match:
        return match.group(1).strip()

    return None


def extract_named_integer(
    output,
    label
):

    value = extract_info_value(
        output,
        label
    )

    if value is None:
        return None

    match = re.search(
        r"([\d,]+)",
        value
    )

    if not match:
        return None

    try:
        return int(
            match.group(1).replace(
                ",",
                ""
            )
        )

    except Exception:
        return None


def extract_named_percent(
    output,
    label
):

    value = extract_info_value(
        output,
        label
    )

    if value is None:
        return None

    match = re.search(
        r"(\d+)\s*%",
        value
    )

    if not match:
        return None

    try:
        return int(
            match.group(1)
        )

    except Exception:
        return None


def determine_smart_health(
    passed,
    reallocated,
    pending,
    uncorrectable
):

    if passed is False:
        return "FAILED"

    values = [
        reallocated,
        pending,
        uncorrectable
    ]

    for value in values:

        if (
            value is not None
            and value > 0
        ):

            return "WARNING"

    if passed is True:
        return "PASSED"

    return "UNKNOWN"


# -------------------------------------------------
# ATA SMART
# -------------------------------------------------

def get_ata_smart(
    device
):

    device_path = f"/dev/{device}"

    result, smart_device_type = run_smartctl_best(
        device,
        [
            "-a"
        ],
        timeout=30,
        stop_on_standby=False
    )

    output = result["output"]

    if not output:

        return {
            "available": False,
            "health": "UNKNOWN"
        }

    health_passed = None

    if (
        "SMART overall-health self-assessment test result: PASSED"
        in output
    ):

        health_passed = True

    elif (
        "SMART overall-health self-assessment test result: FAILED"
        in output
    ):

        health_passed = False

    else:

        scsi_health = re.search(
            r"SMART Health Status:\s*(.+)",
            output,
            re.IGNORECASE
        )

        if scsi_health:

            scsi_health_text = (
                scsi_health.group(1)
                .strip()
                .upper()
            )

            if (
                scsi_health_text == "OK"
                or "PASSED" in scsi_health_text
            ):

                health_passed = True

            elif scsi_health_text:

                health_passed = False

    reallocated = extract_smart_attribute(
        output,
        "Reallocated_Sector_Ct"
    )

    pending = extract_smart_attribute(
        output,
        "Current_Pending_Sector"
    )

    uncorrectable = extract_smart_attribute(
        output,
        "Offline_Uncorrectable"
    )

    crc_errors = extract_smart_attribute(
        output,
        "UDMA_CRC_Error_Count"
    )

    reported_uncorrect = extract_smart_attribute(
        output,
        "Reported_Uncorrect"
    )

    power_cycle_count = extract_smart_attribute(
        output,
        "Power_Cycle_Count"
    )

    start_stop_count = extract_smart_attribute(
        output,
        "Start_Stop_Count"
    )

    load_cycle_count = extract_smart_attribute(
        output,
        "Load_Cycle_Count"
    )

    total_lbas_written = extract_smart_attribute(
        output,
        "Total_LBAs_Written"
    )

    total_lbas_read = extract_smart_attribute(
        output,
        "Total_LBAs_Read"
    )

    power_on_hours = extract_power_on_hours(
        output
    )

    rotation_rate_rpm = extract_rotation_rate_rpm(
        output
    )

    temperature = extract_temperature(
        output
    )

    serial_number = extract_info_value(
        output,
        "Serial Number"
    )

    firmware_version = extract_info_value(
        output,
        "Firmware Version"
    )

    sata_version = extract_info_value(
        output,
        "SATA Version is"
    )

    health = determine_smart_health(
        health_passed,
        reallocated,
        pending,
        uncorrectable
    )

    protocol = (
        "SCSI"
        if smart_device_type == "scsi"
        else "ATA"
    )

    smart_details_limited = (
        protocol == "SCSI"
        and (
            "error counter logging not supported"
            in output.lower()
            or "does not support self test logging"
            in output.lower()
            or (
                reallocated is None
                and pending is None
                and uncorrectable is None
                and power_on_hours is None
            )
        )
    )

    parsed_smart_values = (
        temperature is not None
        or power_on_hours is not None
        or reallocated is not None
        or pending is not None
        or uncorrectable is not None
        or crc_errors is not None
        or reported_uncorrect is not None
        or power_cycle_count is not None
        or start_stop_count is not None
        or load_cycle_count is not None
        or total_lbas_written is not None
        or total_lbas_read is not None
        or serial_number is not None
        or firmware_version is not None
    )

    ata_attributes = extract_ata_smart_attributes(output)

    smart_available = (
        health_passed is not None
        or parsed_smart_values
        or bool(ata_attributes)
        or "SMART support is:     Available"
        in output
        or "SMART support is: Available"
        in output
        or "SMART attributes data structure"
        in output.lower()
        or "NVMe Version"
        in output
    )

    return {
        "available": smart_available,
        "health": health,
        "temperature_celsius": temperature,
        "power_on_hours": power_on_hours,
        "rotation_rate_rpm": rotation_rate_rpm,
        "reallocated_sectors": reallocated,
        "pending_sectors": pending,
        "offline_uncorrectable": uncorrectable,
        "crc_errors": crc_errors,
        "reported_uncorrectable": reported_uncorrect,
        "power_cycles": power_cycle_count,
        "start_stop_count": start_stop_count,
        "load_cycle_count": load_cycle_count,
        "total_lbas_written": total_lbas_written,
        "total_lbas_read": total_lbas_read,
        "serial_number": serial_number,
        "firmware_version": firmware_version,
        "interface_version": sata_version,
        "protocol": protocol,
        "smart_details_limited":
            smart_details_limited,
        "smartctl_device_type": smart_device_type,
        "ata_attributes": ata_attributes,
        "ata_attribute_count": len(ata_attributes)
    }


# -------------------------------------------------
# NVME SMART
# -------------------------------------------------

def get_nvme_smart(
    device
):

    device_path = f"/dev/{device}"

    result, smart_device_type = run_smartctl_best(
        device,
        [
            "-a"
        ],
        timeout=30
    )

    output = result["output"]

    if not output:

        return {
            "available": False,
            "health": "UNKNOWN"
        }

    health = "UNKNOWN"

    if (
        "SMART overall-health self-assessment test result: PASSED"
        in output
    ):

        health = "PASSED"

    elif (
        "SMART overall-health self-assessment test result: FAILED"
        in output
    ):

        health = "FAILED"

    temperature = None

    match = re.search(
        r"Temperature:\s*(\d+)\s*Celsius",
        output,
        re.IGNORECASE
    )

    if match:

        try:
            temperature = int(
                match.group(1)
            )

        except Exception:
            pass

    power_on_hours = None

    match = re.search(
        r"Power On Hours:\s*([\d,]+)",
        output,
        re.IGNORECASE
    )

    if match:

        try:

            power_on_hours = int(
                match.group(1).replace(
                    ",",
                    ""
                )
            )

        except Exception:
            pass

    unsafe_shutdowns = None

    match = re.search(
        r"Unsafe Shutdowns:\s*([\d,]+)",
        output,
        re.IGNORECASE
    )

    if match:

        try:

            unsafe_shutdowns = int(
                match.group(1).replace(
                    ",",
                    ""
                )
            )

        except Exception:
            pass

    media_errors = None

    match = re.search(
        r"Media and Data Integrity Errors:\s*([\d,]+)",
        output,
        re.IGNORECASE
    )

    if match:

        try:

            media_errors = int(
                match.group(1).replace(
                    ",",
                    ""
                )
            )

        except Exception:
            pass

    percentage_used = None

    match = re.search(
        r"Percentage Used:\s*(\d+)%",
        output,
        re.IGNORECASE
    )

    if match:

        try:
            percentage_used = int(
                match.group(1)
            )

        except Exception:
            pass

    serial_number = extract_info_value(
        output,
        "Serial Number"
    )

    firmware_version = extract_info_value(
        output,
        "Firmware Version"
    )

    available_spare = extract_named_percent(
        output,
        "Available Spare"
    )

    available_spare_threshold = extract_named_percent(
        output,
        "Available Spare Threshold"
    )

    critical_warning = extract_info_value(
        output,
        "Critical Warning"
    )

    data_units_read = extract_named_integer(
        output,
        "Data Units Read"
    )

    data_units_written = extract_named_integer(
        output,
        "Data Units Written"
    )

    host_read_commands = extract_named_integer(
        output,
        "Host Read Commands"
    )

    host_write_commands = extract_named_integer(
        output,
        "Host Write Commands"
    )

    controller_busy_time = extract_named_integer(
        output,
        "Controller Busy Time"
    )

    power_cycles = extract_named_integer(
        output,
        "Power Cycles"
    )

    error_information_log_entries = extract_named_integer(
        output,
        "Error Information Log Entries"
    )

    warning_temp_time = extract_named_integer(
        output,
        "Warning  Comp. Temperature Time"
    )

    critical_temp_time = extract_named_integer(
        output,
        "Critical Comp. Temperature Time"
    )

    if (
        health == "PASSED"
        and media_errors is not None
        and media_errors > 0
    ):

        health = "WARNING"

    return {
        "available": True,
        "health": health,
        "temperature_celsius": temperature,
        "power_on_hours": power_on_hours,
        "percentage_used": percentage_used,
        "media_errors": media_errors,
        "unsafe_shutdowns": unsafe_shutdowns,
        "available_spare": available_spare,
        "available_spare_threshold": available_spare_threshold,
        "critical_warning": critical_warning,
        "data_units_read": data_units_read,
        "data_units_written": data_units_written,
        "host_read_commands": host_read_commands,
        "host_write_commands": host_write_commands,
        "controller_busy_time_minutes": controller_busy_time,
        "power_cycles": power_cycles,
        "error_information_log_entries":
            error_information_log_entries,
        "warning_temperature_time_minutes":
            warning_temp_time,
        "critical_temperature_time_minutes":
            critical_temp_time,
        "serial_number": serial_number,
        "firmware_version": firmware_version,
        "protocol": "NVMe",
        "smartctl_device_type": smart_device_type
    }



# -------------------------------------------------
# SMART AUTOMATION
# -------------------------------------------------

def get_smart_automation_slot(
    now_local=None,
    checks_per_day=None
):

    if checks_per_day is None:

        try:

            checks_per_day = int(
                smart_automation_config.get(
                    "checks_per_day",
                    0
                )
            )

        except Exception:

            checks_per_day = 0

    if (
        checks_per_day
        not in SMART_AUTOMATION_ALLOWED_CHECKS_PER_DAY
        or checks_per_day <= 0
    ):

        return None

    if now_local is None:

        now_local = datetime.now().astimezone()

    total_minutes = (
        now_local.hour * 60
        + now_local.minute
    )

    slot_index = min(
        checks_per_day - 1,
        int(
            total_minutes
            * checks_per_day
            / (24 * 60)
        )
    )

    start_minutes = int(
        slot_index
        * (24 * 60)
        / checks_per_day
    )

    end_minutes = int(
        (slot_index + 1)
        * (24 * 60)
        / checks_per_day
    )

    start_hour, start_minute = divmod(
        start_minutes,
        60
    )

    if end_minutes >= 24 * 60:

        end_label = "24:00"

    else:

        end_hour, end_minute = divmod(
            end_minutes,
            60
        )

        end_label = (
            f"{end_hour:02d}:"
            f"{end_minute:02d}"
        )

    start_local = now_local.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0
    )

    return {
        "date": now_local.date().isoformat(),
        "index": slot_index,
        "number": slot_index + 1,
        "checks_per_day": checks_per_day,
        "key": (
            f"{now_local.date().isoformat()}:"
            f"{checks_per_day}:"
            f"{slot_index}"
        ),
        "start": (
            f"{start_hour:02d}:"
            f"{start_minute:02d}"
        ),
        "end": end_label,
        "start_local_iso":
            start_local.isoformat()
    }


def get_smart_automation_stable_id(
    device,
    device_path
):

    cached = smart_cache.get(
        device,
        {}
    )

    if not isinstance(
        cached,
        dict
    ):

        cached = {}

    model = read_file(
        device_path / "device/model"
    )

    vendor = read_file(
        device_path / "device/vendor"
    )

    serial = (
        cached.get(
            "serial_number"
        )
        or read_file(
            device_path / "device/serial"
        )
    )

    return get_disk_stable_id(
        device,
        device_path,
        model=model,
        vendor=vendor,
        serial=serial,
        size_bytes=get_size(
            device_path
        )
    )


def smart_automation_slot_completed(
    device,
    device_path,
    slot
):

    if not slot:
        return True

    stable_id = get_smart_automation_stable_id(
        device,
        device_path
    )

    completed_slots = (
        smart_automation_config.get(
            "completed_slots",
            {}
        )
    )

    completed = (
        completed_slots.get(
            stable_id
        )
        if isinstance(
            completed_slots,
            dict
        )
        else None
    )

    if isinstance(
        completed,
        dict
    ):

        return (
            completed.get(
                "slot"
            )
            == slot.get(
                "key"
            )
            and str(
                completed.get(
                    "source",
                    ""
                )
            ).startswith(
                "automation:"
            )
        )

    return False


def mark_smart_automation_slot_completed(
    device,
    device_path,
    slot,
    source
):

    if not slot:
        return

    stable_id = get_smart_automation_stable_id(
        device,
        device_path
    )

    checked_at = datetime.now(
        timezone.utc
    ).isoformat()

    completed_slots = (
        smart_automation_config.setdefault(
            "completed_slots",
            {}
        )
    )

    completed_slots[
        stable_id
    ] = {
        "slot": slot[
            "key"
        ],
        "checked_at": checked_at,
        "source": source,
        "device": device
    }

    if str(
        source
    ).startswith(
        "automation:"
    ):

        automatic_runs = (
            smart_automation_config.setdefault(
                "automatic_runs",
                {}
            )
        )

        current = automatic_runs.get(
            stable_id
        )

        if (
            not isinstance(
                current,
                dict
            )
            or current.get(
                "date"
            ) != slot.get(
                "date"
            )
        ):

            current = {
                "date": slot.get(
                    "date"
                ),
                "count": 0
            }

        try:
            count = int(
                current.get(
                    "count",
                    0
                )
            ) + 1
        except Exception:
            count = 1

        automatic_runs[
            stable_id
        ] = {
            "date": slot.get(
                "date"
            ),
            "count": count,
            "last_checked": checked_at,
            "last_slot": slot.get(
                "key"
            ),
            "device": device
        }

    save_smart_automation_config()


def get_hdd_last_activity_age_seconds(
    device
):

    activity = disk_activity.get(
        device,
        {}
    )

    last_activity = activity.get(
        "last_activity"
    )

    if not last_activity:
        return None

    try:

        parsed = datetime.fromisoformat(
            last_activity
        )

        if parsed.tzinfo is None:

            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return max(
            0.0,
            (
                datetime.now(
                    timezone.utc
                )
                - parsed.astimezone(
                    timezone.utc
                )
            ).total_seconds()
        )

    except Exception:

        return None


def hdd_is_confirmed_awake_for_automation(
    device,
    device_path
):

    activity = disk_activity.get(
        device,
        {}
    )

    if activity_is_recent(
        activity,
        SMART_AUTOMATION_RECENT_IO_SECONDS
    ):

        return True, "recent-io"

    transport = get_device_transport(
        device,
        device_path
    )

    if transport == "usb":

        runtime_state = get_usb_runtime_power_state(
            device
        )

        if (
            isinstance(
                runtime_state,
                dict
            )
            and runtime_state.get(
                "status"
            )
            == "STANDBY"
        ):

            return False, "usb-runtime-standby"

        stable_id = get_smart_automation_stable_id(
            device,
            device_path
        )

        usb_config = get_usb_standby_config(
            stable_id
        )

        standby_minutes = usb_config.get(
            "minutes"
        )

        activity_age = (
            get_hdd_last_activity_age_seconds(
                device
            )
        )

        if (
            standby_minutes
            and activity_age is not None
            and activity_age
            < max(
                1.0,
                standby_minutes * 60 - 5
            )
        ):

            return (
                True,
                "usb-known-idle-window"
            )

        return False, "usb-awake-unconfirmed"

    # ZimaOS local-storage state is a passive host-side source and does not
    # send a power command to the disk.
    zimaos_state = get_zimaos_standby(
        device
    )

    if zimaos_state.get(
        "available"
    ):

        if zimaos_state.get(
            "standby"
        ) is True:

            return False, "zimaos-standby"

        if zimaos_state.get(
            "standby"
        ) is False:

            return True, "zimaos-active"

    return False, "awake-unconfirmed"


def get_smart_automation_status():

    try:

        checks_per_day = int(
            smart_automation_config.get(
                "checks_per_day",
                0
            )
        )

    except Exception:

        checks_per_day = 0

    if (
        checks_per_day
        not in SMART_AUTOMATION_ALLOWED_CHECKS_PER_DAY
    ):

        checks_per_day = 0

    slot = get_smart_automation_slot(
        checks_per_day=checks_per_day
    )

    pending = []

    now_monotonic = time.monotonic()

    for device, item in list(
        smart_automation_pending.items()
    ):

        if not isinstance(
            item,
            dict
        ):
            continue

        pending.append(
            {
                "device": device,
                "slot":
                    item.get(
                        "slot_key"
                    ),
                "due_in_seconds":
                    max(
                        0,
                        int(
                            item.get(
                                "due_monotonic",
                                now_monotonic
                            )
                            - now_monotonic
                        )
                    )
            }
        )

    today_local = datetime.now(
    ).astimezone().date().isoformat()

    automatic_runs = (
        smart_automation_config.get(
            "automatic_runs",
            {}
        )
    )

    if not isinstance(
        automatic_runs,
        dict
    ):
        automatic_runs = {}

    drives = []

    for device, device_path in get_devices():

        try:
            stable_id = get_smart_automation_stable_id(
                device,
                device_path
            )
        except Exception:
            stable_id = None

        run_info = (
            automatic_runs.get(
                stable_id
            )
            if stable_id
            else None
        )

        if (
            not isinstance(
                run_info,
                dict
            )
            or run_info.get(
                "date"
            ) != today_local
        ):
            run_info = {}

        try:
            today_count = int(
                run_info.get(
                    "count",
                    0
                )
            )
        except Exception:
            today_count = 0

        drives.append(
            {
                "device": device,
                "today_count": max(
                    0,
                    today_count
                ),
                "target_count": checks_per_day,
                "last_automatic_checked":
                    run_info.get(
                        "last_checked"
                    )
            }
        )

    return {
        "enabled": checks_per_day > 0,
        "checks_per_day": checks_per_day,
        "allowed_checks_per_day": [0, 1, 2, 3],
        "wake_delay_seconds":
            SMART_AUTOMATION_WAKE_DELAY_SECONDS,
        "no_wake": True,
        "startup_check": True,
        "current_slot": slot,
        "pending": pending,
        "drives": drives
    }


async def run_startup_smart_check():

    # Let the passive activity monitor establish its first baseline before
    # deciding whether an HDD is definitely awake.
    await asyncio.sleep(
        3
    )

    slot = get_smart_automation_slot()

    for device, device_path in get_devices():

        try:

            disk_type = get_disk_type(
                device,
                device_path
            )

            should_read = (
                disk_type
                in (
                    "SSD",
                    "FLASH"
                )
            )

            awake_reason = None

            if disk_type == "HDD":

                (
                    should_read,
                    awake_reason
                ) = (
                    hdd_is_confirmed_awake_for_automation(
                        device,
                        device_path
                    )
                )

            if not should_read:
                continue

            await asyncio.to_thread(
                read_smart_now,
                device,
                "startup"
            )


        except Exception:
            pass

        await asyncio.sleep(
            0.25
        )


async def monitor_smart_automation():

    while True:

        try:

            checks_per_day = int(
                smart_automation_config.get(
                    "checks_per_day",
                    0
                )
            )

        except Exception:

            checks_per_day = 0

        if checks_per_day <= 0:

            smart_automation_pending.clear()

            await asyncio.sleep(
                SMART_AUTOMATION_POLL_SECONDS
            )

            continue

        slot = get_smart_automation_slot(
            checks_per_day=checks_per_day
        )

        if not slot:

            await asyncio.sleep(
                SMART_AUTOMATION_POLL_SECONDS
            )

            continue

        known_devices = {
            name: path
            for name, path in get_devices()
        }

        now_monotonic = time.monotonic()

        # Remove pending entries from an old window or removed device.
        for device in list(
            smart_automation_pending.keys()
        ):

            item = smart_automation_pending.get(
                device,
                {}
            )

            if (
                device not in known_devices
                or item.get(
                    "slot_key"
                )
                != slot[
                    "key"
                ]
            ):

                smart_automation_pending.pop(
                    device,
                    None
                )

        for device, device_path in known_devices.items():

            try:

                disk_type = get_disk_type(
                    device,
                    device_path
                )

                if smart_automation_slot_completed(
                    device,
                    device_path,
                    slot
                ):

                    smart_automation_pending.pop(
                        device,
                        None
                    )

                    continue

                if disk_type in (
                    "SSD",
                    "FLASH"
                ):

                    await asyncio.to_thread(
                        read_smart_now,
                        device,
                        "automation-scheduled"
                    )

                    mark_smart_automation_slot_completed(
                        device,
                        device_path,
                        slot,
                        "automation:scheduled"
                    )

                    smart_automation_pending.pop(
                        device,
                        None
                    )

                    continue

                if disk_type != "HDD":
                    continue

                pending = smart_automation_pending.get(
                    device
                )

                if not pending:

                    if activity_is_recent(
                        disk_activity.get(
                            device,
                            {}
                        ),
                        SMART_AUTOMATION_RECENT_IO_SECONDS
                    ):

                        smart_automation_pending[
                            device
                        ] = {
                            "slot_key":
                                slot[
                                    "key"
                                ],
                            "triggered_at":
                                datetime.now(
                                    timezone.utc
                                ).isoformat(),
                            "due_monotonic":
                                (
                                    now_monotonic
                                    + SMART_AUTOMATION_WAKE_DELAY_SECONDS
                                )
                        }

                    continue

                if (
                    now_monotonic
                    < pending.get(
                        "due_monotonic",
                        now_monotonic
                    )
                ):

                    continue

                (
                    confirmed_awake,
                    awake_reason
                ) = (
                    hdd_is_confirmed_awake_for_automation(
                        device,
                        device_path
                    )
                )

                if not confirmed_awake:

                    # Do not risk waking it. The next real I/O event in the
                    # same window can arm a fresh delayed attempt.
                    smart_automation_pending.pop(
                        device,
                        None
                    )

                    continue

                await asyncio.to_thread(
                    read_smart_now,
                    device,
                    "automation-natural-wake"
                )

                mark_smart_automation_slot_completed(
                    device,
                    device_path,
                    slot,
                    (
                        "automation:"
                        + str(
                            awake_reason
                        )
                    )
                )

                smart_automation_pending.pop(
                    device,
                    None
                )

            except Exception:

                smart_automation_pending.pop(
                    device,
                    None
                )

            await asyncio.sleep(
                0.1
            )

        await asyncio.sleep(
            SMART_AUTOMATION_POLL_SECONDS
        )


# -------------------------------------------------
# SMART HISTORY
# -------------------------------------------------

SMART_HISTORY_FIELDS = [
    "temperature_celsius",
    "power_on_hours",
    "power_cycles",
    "reallocated_sectors",
    "pending_sectors",
    "offline_uncorrectable",
    "crc_errors",
    "reported_uncorrectable",
    "start_stop_count",
    "load_cycle_count",
    "total_lbas_written",
    "total_lbas_read",
    "percentage_used",
    "media_errors",
    "unsafe_shutdowns",
    "available_spare",
    "data_units_read",
    "data_units_written",
    "error_information_log_entries",
    "controller_busy_time_minutes"
]


def smart_history_connect():

    SMART_HISTORY_DB_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    connection = sqlite3.connect(
        SMART_HISTORY_DB_FILE,
        timeout=10
    )

    connection.row_factory = sqlite3.Row

    return connection


def init_smart_history_db():

    with smart_history_connect() as connection:

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS smart_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                stable_id TEXT NOT NULL,
                device TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                protocol TEXT,
                health TEXT,
                temperature_celsius REAL,
                power_on_hours INTEGER,
                power_cycles INTEGER,
                reallocated_sectors INTEGER,
                pending_sectors INTEGER,
                offline_uncorrectable INTEGER,
                crc_errors INTEGER,
                reported_uncorrectable INTEGER,
                start_stop_count INTEGER,
                load_cycle_count INTEGER,
                total_lbas_written INTEGER,
                total_lbas_read INTEGER,
                percentage_used REAL,
                media_errors INTEGER,
                unsafe_shutdowns INTEGER,
                critical_warning TEXT,
                available_spare REAL,
                data_units_read INTEGER,
                data_units_written INTEGER,
                error_information_log_entries INTEGER,
                controller_busy_time_minutes INTEGER,
                source TEXT NOT NULL DEFAULT 'smart-read'
            )
            """
        )

        connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                idx_smart_history_unique_sample
            ON smart_history (
                stable_id,
                recorded_at
            )
            """
        )

        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS
                idx_smart_history_device_time
            ON smart_history (
                stable_id,
                recorded_at
            )
            """
        )

        connection.commit()


def get_smart_history_stable_id(
    device,
    smart=None
):

    device_path = SYS_BLOCK / device

    model = read_file(
        device_path / "device/model"
    )

    vendor = read_file(
        device_path / "device/vendor"
    )

    size_bytes = get_size(
        device_path
    )

    smart = smart or {}

    serial = (
        read_file(
            device_path / "device/serial"
        )
        or smart.get(
            "serial_number"
        )
        or smart_cache.get(
            device,
            {}
        ).get(
            "serial_number"
        )
    )

    return get_disk_stable_id(
        device,
        device_path,
        model=model,
        vendor=vendor,
        serial=serial,
        size_bytes=size_bytes
    )


def record_smart_history(
    device,
    smart,
    source="smart-read",
    recorded_at=None
):

    if not isinstance(
        smart,
        dict
    ):
        return False

    # Some USB/SCSI bridges expose useful SMART values but do not report
    # the classic SMART capability strings used by smartctl on native ATA.
    # In that case smart["available"] can be False even though temperature,
    # power-on hours, sector counters, etc. were parsed successfully.
    #
    # For history we therefore store a sample whenever at least one real
    # history metric is present. This does not generate any extra SMART read;
    # it only persists values from a read that already happened.
    has_history_value = any(
        smart.get(
            field
        )
        is not None
        for field in SMART_HISTORY_FIELDS
    )

    if not has_history_value:
        return False

    stable_id = get_smart_history_stable_id(
        device,
        smart
    )

    if not stable_id:
        return False

    recorded_at = (
        recorded_at
        or smart.get(
            "last_checked"
        )
        or datetime.now(
            timezone.utc
        ).isoformat()
    )

    with smart_history_connect() as connection:

        connection.execute(
            """
            INSERT OR IGNORE INTO smart_history (
                stable_id,
                device,
                recorded_at,
                protocol,
                health,
                temperature_celsius,
                power_on_hours,
                power_cycles,
                reallocated_sectors,
                pending_sectors,
                offline_uncorrectable,
                crc_errors,
                reported_uncorrectable,
                start_stop_count,
                load_cycle_count,
                total_lbas_written,
                total_lbas_read,
                percentage_used,
                media_errors,
                unsafe_shutdowns,
                critical_warning,
                available_spare,
                data_units_read,
                data_units_written,
                error_information_log_entries,
                controller_busy_time_minutes,
                source
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                stable_id,
                device,
                recorded_at,
                smart.get("protocol"),
                smart.get("health"),
                smart.get("temperature_celsius"),
                smart.get("power_on_hours"),
                smart.get("power_cycles"),
                smart.get("reallocated_sectors"),
                smart.get("pending_sectors"),
                smart.get("offline_uncorrectable"),
                smart.get("crc_errors"),
                smart.get("reported_uncorrectable"),
                smart.get("start_stop_count"),
                smart.get("load_cycle_count"),
                smart.get("total_lbas_written"),
                smart.get("total_lbas_read"),
                smart.get("percentage_used"),
                smart.get("media_errors"),
                smart.get("unsafe_shutdowns"),
                smart.get("critical_warning"),
                smart.get("available_spare"),
                smart.get("data_units_read"),
                smart.get("data_units_written"),
                smart.get("error_information_log_entries"),
                smart.get("controller_busy_time_minutes"),
                source
            )
        )

        connection.commit()

    return True


def prune_smart_history():

    cutoff = datetime.fromtimestamp(
        time.time()
        - SMART_HISTORY_RETENTION_DAYS
        * 24
        * 60
        * 60,
        timezone.utc
    ).isoformat()

    with smart_history_connect() as connection:

        connection.execute(
            """
            DELETE FROM smart_history
            WHERE recorded_at < ?
            """,
            (cutoff,)
        )

        connection.commit()


def seed_smart_history_from_cache():

    for device, smart in list(
        smart_cache.items()
    ):

        if not isinstance(
            smart,
            dict
        ):
            continue

        timestamp = smart.get(
            "last_checked"
        )

        if not timestamp:
            continue

        try:

            record_smart_history(
                device,
                smart,
                source="cache-seed",
                recorded_at=timestamp
            )

        except Exception:
            pass


def get_smart_history_range_seconds(
    range_name
):

    return {
        "24h": 24 * 60 * 60,
        "7d": 7 * 24 * 60 * 60,
        "30d": 30 * 24 * 60 * 60,
        "1y": 365 * 24 * 60 * 60
    }.get(
        range_name,
        7 * 24 * 60 * 60
    )


def get_smart_history(
    device,
    range_name
):

    known_devices = {
        name: path
        for name, path in get_devices()
    }

    if device not in known_devices:
        return None

    smart = smart_cache.get(
        device,
        {}
    )

    stable_id = get_smart_history_stable_id(
        device,
        smart
    )

    cutoff = datetime.fromtimestamp(
        time.time()
        - get_smart_history_range_seconds(
            range_name
        ),
        timezone.utc
    ).isoformat()

    with smart_history_connect() as connection:

        rows = connection.execute(
            """
            SELECT
                recorded_at,
                protocol,
                health,
                temperature_celsius,
                power_on_hours,
                power_cycles,
                reallocated_sectors,
                pending_sectors,
                offline_uncorrectable,
                crc_errors,
                reported_uncorrectable,
                start_stop_count,
                load_cycle_count,
                total_lbas_written,
                total_lbas_read,
                percentage_used,
                media_errors,
                unsafe_shutdowns,
                critical_warning,
                available_spare,
                data_units_read,
                data_units_written,
                error_information_log_entries,
                controller_busy_time_minutes,
                source
            FROM smart_history
            WHERE
                stable_id = ?
                AND recorded_at >= ?
            ORDER BY recorded_at ASC
            LIMIT ?
            """,
            (
                stable_id,
                cutoff,
                SMART_HISTORY_MAX_API_POINTS
            )
        ).fetchall()

    samples = [
        dict(row)
        for row in rows
    ]

    available_metrics = []

    for field in SMART_HISTORY_FIELDS:

        if any(
            sample.get(field) is not None
            for sample in samples
        ):

            available_metrics.append(
                field
            )

    return {
        "device": device,
        "stable_id": stable_id,
        "range": range_name,
        "no_wake_policy": True,
        "automatic_hdd_reads": False,
        "safe_ssd_interval_seconds":
            SMART_HISTORY_SAFE_INTERVAL_SECONDS,
        "sample_count": len(samples),
        "available_metrics": available_metrics,
        "samples": samples
    }


async def monitor_safe_smart_history():

    while True:

        now = time.time()

        for device, device_path in get_devices():

            disk_type = get_disk_type(
                device,
                device_path
            )

            # Never automatically query SMART on mechanical HDDs,
            # including USB HDDs.
            if disk_type not in (
                "SSD",
                "FLASH"
            ):
                continue

            last_read = smart_history_last_auto_read.get(
                device,
                0
            )

            if (
                now - last_read
                < SMART_HISTORY_SAFE_INTERVAL_SECONDS
            ):
                continue

            smart_history_last_auto_read[
                device
            ] = now

            try:

                await asyncio.to_thread(
                    read_smart_now,
                    device,
                    "history-auto"
                )

            except Exception:
                pass

            await asyncio.sleep(
                1
            )

        prune_smart_history()

        await asyncio.sleep(
            60
        )



# -------------------------------------------------
# SMART
# -------------------------------------------------

def read_smart_now(
    device,
    history_source="smart-read"
):

    if device.startswith("nvme"):

        smart = get_nvme_smart(
            device
        )

    else:

        smart = get_ata_smart(
            device
        )

    smart["status"] = "AVAILABLE"

    smart["last_checked"] = datetime.now(
        timezone.utc
    ).isoformat()

    smart["cached"] = False

    smart_cache[device] = dict(
        smart
    )

    save_smart_cache()

    try:

        record_smart_history(
            device,
            smart,
            source=history_source
        )

    except Exception:
        pass

    return smart


def get_smart_data(
    device,
    disk_type,
    power_state
):

    last_checked = datetime.now(
        timezone.utc
    ).isoformat()

    cached = smart_cache.get(
        device
    )

    power_status = power_state.get(
        "status"
    )

    # SSD/NVMe and removable flash media have no mechanical HDD
    # standby state to preserve. Read once automatically, then serve
    # the cache until a manual refresh.
    if disk_type in (
        "SSD",
        "FLASH"
    ):

        if cached is None:

            return read_smart_now(
                device
            )

        result = dict(
            cached
        )

        result["cached"] = True

        return result

    # Mechanical HDD SMART is cache/manual-only during normal monitoring.
    # This avoids SMART traffic becoming a wake event or resetting idle timers
    # on controllers/bridges with unusual power-management behavior.

    if cached is not None:

        result = dict(
            cached
        )

        result["cached"] = True

        if (
            disk_type == "HDD"
            and power_status in (
                "STANDBY",
                "STANDBY_ESTIMATED",
                "STANDBY_WAITING",
                "INACTIVE",
                "UNKNOWN_IDLE"
            )
        ):

            result["power_state_at_display"] = (
                power_status
            )

            result["message"] = (
                "Cached SMART data is shown. "
                "The disk was not queried again."
            )

        return result

    if (
        disk_type == "HDD"
        and power_status == "STANDBY"
    ):

        return {
            "available": True,
            "status": "STANDBY",
            "health": "STANDBY",
            "message": (
                "Disk is in standby. "
                "SMART data was not queried "
                "to avoid waking the disk."
            ),
            "last_checked": None,
            "cached": False
        }

    # No cache and no definitely-safe state: do not issue SMART.
    return {
        "available": False,
        "status": "NOT_QUERIED",
        "health": "UNKNOWN",
        "message": (
            "SMART data has not been queried yet. "
            "Use the manual SMART action to read it."
        ),
        "last_checked": None,
        "cached": False
    }


# -------------------------------------------------
# DISK LIST
# -------------------------------------------------

def get_disks():

    disks = []

    mounts = get_mounts()

    raid_topology = (
        get_raid_topology(
            mounts
        )
    )

    for device, device_path in get_devices():

        size_bytes = get_size(
            device_path
        )

        disk_type = get_disk_type(
            device,
            device_path
        )

        direct_mountpoints = get_disk_mountpoints(
            device_path,
            device,
            mounts
        )

        raid_memberships = (
            get_raid_memberships_for_device(
                device,
                raid_topology
            )
        )

        mountpoints = (
            get_effective_mountpoints(
                direct_mountpoints,
                raid_memberships
            )
        )

        activity = disk_activity.get(
            device,
            {
                "status": "UNKNOWN",
                "read_bytes_per_sec": 0,
                "write_bytes_per_sec": 0,
                "read_ops_per_sec": 0,
                "write_ops_per_sec": 0,
                "last_activity": None,
                "idle_since": APP_STARTED_AT
            }
        )

        model = read_file(
            device_path / "device/model"
        )

        vendor = read_file(
            device_path / "device/vendor"
        )

        transport = get_device_transport(
            device,
            device_path
        )

        cached_serial = (
            smart_cache.get(
                device,
                {}
            ).get(
                "serial_number"
            )
        )

        serial = (
            read_file(
                device_path / "device/serial"
            )
            or cached_serial
        )

        stable_id = get_disk_stable_id(
            device,
            device_path,
            model=model,
            vendor=vendor,
            serial=serial,
            size_bytes=size_bytes
        )

        usb_standby_config = (
            get_usb_standby_config(
                stable_id
            )
            if (
                transport == "usb"
                and disk_type == "HDD"
            )
            else {
                "minutes": None,
                "configured": False
            }
        )

        power_state = check_power_state(
            device,
            disk_type,
            activity,
            transport=transport,
            usb_standby_minutes=
                usb_standby_config.get(
                    "minutes"
                )
        )

        smart = get_smart_data(
            device,
            disk_type,
            power_state
        )

        if not serial:

            serial = smart.get(
                "serial_number"
            )

            if serial:

                stable_id = get_disk_stable_id(
                    device,
                    device_path,
                    model=model,
                    vendor=vendor,
                    serial=serial,
                    size_bytes=size_bytes
                )

                if (
                    transport == "usb"
                    and disk_type == "HDD"
                ):

                    usb_standby_config = (
                        get_usb_standby_config(
                            stable_id
                        )
                    )

        activity_payload = dict(
            activity
        )

        activity_payload[
            "idle_seconds"
        ] = round(
            get_activity_idle_seconds(
                activity
            ),
            1
        )

        disks.append(
            {
                "device": device,

                "path": f"/dev/{device}",

                "type": disk_type,

                "transport": transport,

                "stable_id": stable_id,

                "usb_standby_config":
                    usb_standby_config,

                "model": model,

                "vendor": vendor,

                "serial": serial,

                "firmware": (
                    read_file(
                        device_path / "device/firmware_rev"
                    )
                    or read_file(
                        device_path / "device/rev"
                    )
                    or smart.get(
                        "firmware_version"
                    )
                ),

                "size_bytes": size_bytes,

                "size_gb": round(
                    size_bytes / 1000**3,
                    2
                ),

                "size_tb": round(
                    size_bytes / 1000**4,
                    2
                ),

                "partitions": get_partitions(
                    device_path,
                    device
                ),

                "direct_mountpoints":
                    direct_mountpoints,

                "direct_filesystems":
                    get_filesystems_for_mountpoints(
                        direct_mountpoints
                    ),

                "mountpoints": mountpoints,

                "filesystems":
                    get_filesystems_for_mountpoints(
                        mountpoints
                    ),

                "display_mountpoint":
                    get_display_mountpoint(
                        mountpoints
                    ),

                "raid_memberships":
                    raid_memberships,

                "is_raid_member": bool(
                    raid_memberships
                ),

                "activity":
                    activity_payload,

                "current_access":
                    get_current_process_access(
                        device
                    ),

                "power_state": power_state,

                "smart": smart
            }
        )

    return sorted(
        disks,
        key=lambda x: x["device"]
    )


# -------------------------------------------------
# MANUAL HDD STANDBY
# -------------------------------------------------

def disk_has_immediate_io(
    device_path,
    sample_seconds=0.35
):

    first = read_disk_stats(
        device_path
    )

    if first is None:
        return None

    time.sleep(
        sample_seconds
    )

    second = read_disk_stats(
        device_path
    )

    if second is None:
        return None

    return (
        second["reads"] > first["reads"]
        or second["writes"] > first["writes"]
        or (
            second["sectors_read"]
            > first["sectors_read"]
        )
        or (
            second["sectors_written"]
            > first["sectors_written"]
        )
    )


def get_smartctl_device_type_candidates(
    device
):

    candidates = []

    cached_type = (
        smart_cache.get(
            device,
            {}
        ).get(
            "smartctl_device_type"
        )
    )

    if cached_type:
        candidates.append(
            cached_type
        )

    candidates.extend(
        [
            None,
            "sat",
            "sat,12",
            "sat,16",
            "scsi"
        ]
    )

    unique = []

    for candidate in candidates:

        if candidate in unique:
            continue

        unique.append(
            candidate
        )

    return unique


def run_smartctl_for_type(
    device,
    options,
    device_type=None,
    timeout=15
):

    command = [
        "smartctl"
    ]

    command.extend(
        options
    )

    if device_type:

        command.extend(
            [
                "-d",
                device_type
            ]
        )

    command.append(
        f"/dev/{device}"
    )

    return run_command(
        command,
        timeout=timeout
    )



def verify_disk_standby(
    device,
    preferred_smartctl_type=None
):

    device_sys_path = (
        SYS_BLOCK
        / device
    )

    transport = get_device_transport(
        device,
        device_sys_path
    )

    if transport == "usb":

        smart_power = get_smartctl_power_state(
            device,
            preferred_device_type=
                preferred_smartctl_type,
            force=True
        )

        if smart_power.get(
            "available"
        ):

            return {
                "verified": (
                    smart_power.get(
                        "status"
                    )
                    == "STANDBY"
                ),
                "method":
                    smart_power.get(
                        "method"
                    )
            }

    zimaos_state = get_zimaos_standby(
        device
    )

    if (
        zimaos_state.get(
            "available"
        )
        and zimaos_state.get(
            "standby"
        )
    ):

        return {
            "verified": True,
            "method": "zimaos-local-storage"
        }

    if transport != "usb":

        smart_power = get_smartctl_power_state(
            device,
            preferred_device_type=
                preferred_smartctl_type
        )

        if (
            smart_power.get(
                "available"
            )
            and smart_power.get(
                "status"
            ) == "STANDBY"
        ):

            return {
                "verified": True,
                "method":
                    smart_power.get(
                        "method"
                    )
            }

    result = run_command(
        [
            "hdparm",
            "-C",
            f"/dev/{device}"
        ],
        timeout=10
    )

    output = result.get(
        "output_lower",
        ""
    )

    if (
        "drive state is: standby"
        in output
        or "drive state is: sleeping"
        in output
    ):

        return {
            "verified": True,
            "method": "hdparm"
        }

    return {
        "verified": False,
        "method": None
    }


def try_smartctl_standby(
    device
):

    attempts = []

    for device_type in (
        get_smartctl_device_type_candidates(
            device
        )
    ):

        result = run_smartctl_for_type(
            device,
            [
                "-s",
                "standby,now"
            ],
            device_type=device_type,
            timeout=15
        )

        attempts.append(
            {
                "device_type":
                    device_type,
                "returncode":
                    result.get(
                        "returncode"
                    )
            }
        )

        # Give USB bridges a short moment to complete the power command.
        time.sleep(
            0.35
        )

        verification = verify_disk_standby(
            device,
            preferred_smartctl_type=
                device_type
        )

        if verification.get(
            "verified"
        ):

            return {
                "success": True,
                "device_type":
                    device_type,
                "verification":
                    verification,
                "attempts":
                    attempts
            }

    return {
        "success": False,
        "attempts": attempts
    }


def put_hdd_in_standby(
    device,
    device_path
):

    transport = get_device_transport(
        device,
        device_path
    )

    if transport == "usb":

        current_power = get_usb_runtime_power_state(
            device
        )

        if (
            current_power is not None
            and current_power.get(
                "status"
            ) == "STANDBY"
        ):

            return {
                "success": True,
                "already_standby": True,
                "verified": True,
                "standby_method": None,
                "verification_method":
                    current_power.get(
                        "method"
                    )
            }

    else:

        current_power = get_zimaos_standby(
            device
        )

        if (
            current_power.get(
                "available"
            )
            and current_power.get(
                "standby"
            )
        ):

            return {
                "success": True,
                "already_standby": True,
                "verified": True,
                "standby_method": None,
                "verification_method":
                    "zimaos-local-storage"
            }

    cached_access = get_current_process_access(
        device
    )

    if cached_access:

        return {
            "success": False,
            "reason": "busy_process"
        }

    immediate_io = disk_has_immediate_io(
        device_path
    )

    if immediate_io is True:

        return {
            "success": False,
            "reason": "busy_io"
        }

    if (
        immediate_io is None
        and disk_activity.get(
            device,
            {}
        ).get(
            "status"
        ) == "ACTIVE"
    ):

        return {
            "success": False,
            "reason": "activity_unknown"
        }

    manual_awake_until.pop(
        device,
        None
    )


    # For tested USB HDDs, smartctl -s standby,now is the proven command.
    # Do not send hdparm first through the USB bridge.
    if transport == "usb":

        clear_usb_runtime_power_state(
            device
        )

        smartctl_result = try_smartctl_standby(
            device
        )

        if smartctl_result.get(
            "success"
        ):

            verification = smartctl_result.get(
                "verification",
                {}
            )

            device_type = smartctl_result.get(
                "device_type"
            )

            set_usb_runtime_power_state(
                device,
                "STANDBY",
                "manual-smartctl-standby",
                device_type=device_type
            )

            return {
                "success": True,
                "already_standby": False,
                "verified": True,
                "standby_method": (
                    "smartctl"
                    if not device_type
                    else (
                        "smartctl -d "
                        + device_type
                    )
                ),
                "verification_method":
                    verification.get(
                        "method"
                    )
            }

        clear_usb_runtime_power_state(
            device
        )

        return {
            "success": False,
            "reason": "not_verified",
            "smartctl_attempts":
                smartctl_result.get(
                    "attempts",
                    []
                )
        }

    # Direct SATA/SAS HDDs keep hdparm as first choice.
    hdparm_result = run_command(
        [
            "hdparm",
            "-y",
            f"/dev/{device}"
        ],
        timeout=12
    )

    if (
        hdparm_result.get(
            "returncode"
        ) == 0
    ):

        for _ in range(6):

            time.sleep(
                0.4
            )

            verification = verify_disk_standby(
                device
            )

            if verification.get(
                "verified"
            ):

                return {
                    "success": True,
                    "already_standby": False,
                    "verified": True,
                    "standby_method":
                        "hdparm",
                    "verification_method":
                        verification.get(
                            "method"
                        )
                }

    smartctl_result = try_smartctl_standby(
        device
    )

    if smartctl_result.get(
        "success"
    ):

        verification = smartctl_result.get(
            "verification",
            {}
        )

        device_type = smartctl_result.get(
            "device_type"
        )

        return {
            "success": True,
            "already_standby": False,
            "verified": True,
            "standby_method": (
                "smartctl"
                if not device_type
                else (
                    "smartctl -d "
                    + device_type
                )
            ),
            "verification_method":
                verification.get(
                    "method"
                )
        }

    return {
        "success": False,
        "reason": "not_verified",
        "hdparm_returncode":
            hdparm_result.get(
                "returncode"
            ),
        "smartctl_attempts":
            smartctl_result.get(
                "attempts",
                []
            )
    }


# -------------------------------------------------
# FRONTEND
# -------------------------------------------------

@app.get(
    "/",
    include_in_schema=False
)
def root():

    return FileResponse(
        STATIC_DIR / "index.html"
    )


@app.get(
    "/favicon.ico",
    include_in_schema=False
)
def favicon():

    return FileResponse(
        STATIC_DIR / "favicon.ico",
        media_type="image/x-icon"
    )


@app.get(
    "/favicon-16x16.png",
    include_in_schema=False
)
def favicon_png_16():

    return FileResponse(
        STATIC_DIR / "favicon-16x16.png",
        media_type="image/png"
    )


@app.get(
    "/favicon-32x32.png",
    include_in_schema=False
)
def favicon_png():

    return FileResponse(
        STATIC_DIR / "favicon-32x32.png",
        media_type="image/png"
    )


@app.get(
    "/apple-touch-icon.png",
    include_in_schema=False
)
def apple_touch_icon():

    return FileResponse(
        STATIC_DIR / "apple-touch-icon.png",
        media_type="image/png"
    )


@app.get(
    "/android-chrome-192x192.png",
    include_in_schema=False
)
def android_chrome_icon():

    return FileResponse(
        STATIC_DIR / "android-chrome-192x192.png",
        media_type="image/png"
    )


@app.get(
    "/web-app-icon-512.png",
    include_in_schema=False
)
def web_app_icon():

    return FileResponse(
        STATIC_DIR / "web-app-icon-512.png",
        media_type="image/png"
    )


@app.get(
    "/site.webmanifest",
    include_in_schema=False
)
def web_manifest():

    return FileResponse(
        STATIC_DIR / "site.webmanifest",
        media_type="application/manifest+json"
    )


# -------------------------------------------------
# AUTH API
# -------------------------------------------------

@app.get("/api/auth/status")
def auth_status(
    request: Request
):

    authenticated = is_authenticated(
        request
    )

    return {
        "authenticated": authenticated,

        "username": (
            request.session.get("username")
            if authenticated
            else None
        )
    }


@app.post("/api/login")
def login(
    data: LoginRequest,
    request: Request
):

    client_key = get_login_client_key(
        request
    )

    if login_rate_limited(
        client_key
    ):

        raise HTTPException(
            status_code=429,
            detail="Too many failed login attempts. Try again later."
        )

    username_valid = secrets.compare_digest(
        data.username,
        DISK_MONITOR_USERNAME
    )

    password_valid = secrets.compare_digest(
        data.password,
        DISK_MONITOR_PASSWORD
    )

    if not (
        username_valid
        and password_valid
    ):

        record_login_failure(
            client_key
        )

        raise HTTPException(
            status_code=401,
            detail="Invalid username or password"
        )

    clear_login_failures(
        client_key
    )

    request.session["authenticated"] = True

    request.session["username"] = (
        DISK_MONITOR_USERNAME
    )

    return {
        "success": True,
        "username": DISK_MONITOR_USERNAME
    }


@app.post("/api/logout")
def logout(
    request: Request
):

    request.session.clear()

    return {
        "success": True
    }


# -------------------------------------------------
# DISK API
# -------------------------------------------------

@app.get("/api/disks")
def disks(
    request: Request
):

    require_auth(
        request
    )

    disk_list = get_disks()

    standby_timer = (
        get_zimaos_standby_timer()
    )

    storage_usage = (
        get_storage_usage_summary(
            disk_list
        )
    )

    return {
        "count": len(disk_list),
        "disks": disk_list,
        "standby_timer": standby_timer,
        "storage_usage": storage_usage,
        "resource_usage": get_resource_usage(),
        "service_runtime": get_service_runtime(),
        "smart_automation": get_smart_automation_status()
    }



@app.get("/api/smart/automation")
def smart_automation_status(
    request: Request
):

    require_auth(
        request
    )

    return get_smart_automation_status()


@app.post("/api/smart/automation")
def update_smart_automation(
    payload: SmartAutomationRequest,
    request: Request
):

    require_auth(
        request
    )

    try:

        checks_per_day = int(
            payload.checks_per_day
        )

    except Exception:

        checks_per_day = -1

    if (
        checks_per_day
        not in SMART_AUTOMATION_ALLOWED_CHECKS_PER_DAY
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "reason":
                    "invalid_checks_per_day",
                "allowed":
                    [0, 1, 2, 3]
            }
        )

    previous_checks_per_day = int(
        smart_automation_config.get(
            "checks_per_day",
            0
        )
        or 0
    )

    smart_automation_config[
        "checks_per_day"
    ] = checks_per_day

    if checks_per_day != previous_checks_per_day:
        smart_automation_config[
            "automatic_runs"
        ] = {}
        smart_automation_config[
            "completed_slots"
        ] = {}
        smart_automation_pending.clear()

    if checks_per_day <= 0:

        smart_automation_pending.clear()

    save_smart_automation_config()

    return get_smart_automation_status()


@app.post("/api/zimaos/standby-timer")
def update_zimaos_standby_timer(
    payload: ZimaOsStandbyTimerRequest,
    request: Request
):

    require_auth(
        request
    )

    level = int(
        payload.level
    )

    if (
        level
        not in ZIMAOS_STANDBY_ALLOWED_LEVELS
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "reason": "invalid_level",
                "allowed_levels": sorted(
                    ZIMAOS_STANDBY_ALLOWED_LEVELS
                )
            }
        )

    result = set_zimaos_standby_timer(
        level
    )

    if not result.get(
        "success"
    ):

        raise HTTPException(
            status_code=502,
            detail={
                "reason":
                    result.get(
                        "reason"
                    )
                    or "zimaos_write_failed",
                "requested_level":
                    result.get(
                        "requested_level"
                    ),
                "readback_level":
                    result.get(
                        "readback_level"
                    ),
                "put_status":
                    result.get(
                        "put_status"
                    )
            }
        )

    return result


@app.post("/api/disks/{device}/usb-standby-config")
def update_usb_standby_config(
    device: str,
    payload: UsbStandbyConfigRequest,
    request: Request
):

    require_auth(
        request
    )

    known_devices = {
        name: path
        for name, path in get_devices()
    }

    if device not in known_devices:

        raise HTTPException(
            status_code=404,
            detail={
                "reason": "not_found"
            }
        )

    device_path = known_devices[
        device
    ]

    disk_type = get_disk_type(
        device,
        device_path
    )

    transport = get_device_transport(
        device,
        device_path
    )

    if (
        disk_type != "HDD"
        or transport != "usb"
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "reason":
                    "not_usb_hdd"
            }
        )

    minutes = payload.minutes

    if (
        minutes is not None
        and not (
            1 <= minutes <= 1440
        )
    ):

        raise HTTPException(
            status_code=400,
            detail={
                "reason":
                    "invalid_minutes"
            }
        )

    model = read_file(
        device_path / "device/model"
    )

    vendor = read_file(
        device_path / "device/vendor"
    )

    size_bytes = get_size(
        device_path
    )

    serial = (
        read_file(
            device_path / "device/serial"
        )
        or smart_cache.get(
            device,
            {}
        ).get(
            "serial_number"
        )
    )

    stable_id = get_disk_stable_id(
        device,
        device_path,
        model=model,
        vendor=vendor,
        serial=serial,
        size_bytes=size_bytes
    )

    set_usb_standby_config(
        stable_id,
        minutes
    )

    return {
        "success": True,
        "device": device,
        "stable_id": stable_id,
        "usb_standby_config":
            get_usb_standby_config(
                stable_id
            )
    }


def get_raid_manual_standby_precheck(
    raid_device,
    raid,
    known_devices
):

    raid_path = (
        SYS_BLOCK / raid_device
    )

    array_state = (
        read_file(
            raid_path / "md/array_state"
        )
        or ""
    ).strip().lower()

    sync_action = (
        read_file(
            raid_path / "md/sync_action"
        )
        or "idle"
    ).strip().lower()

    degraded_raw = read_file(
        raid_path / "md/degraded"
    )

    try:
        degraded = int(
            degraded_raw
            if degraded_raw is not None
            else 0
        )
    except Exception:
        degraded = None

    if degraded is None or degraded != 0:
        return {
            "success": False,
            "reason": "raid_degraded",
            "array_state": array_state or None,
            "sync_action": sync_action or None,
            "degraded": degraded
        }

    if sync_action != "idle":
        return {
            "success": False,
            "reason": "raid_sync_active",
            "array_state": array_state or None,
            "sync_action": sync_action or None,
            "degraded": degraded
        }

    # md exposes several states. For a manual all-member standby action we
    # deliberately accept only states that indicate no pending writes.
    if array_state not in {
        "clean",
        "active-idle"
    }:
        return {
            "success": False,
            "reason": "raid_state_not_safe",
            "array_state": array_state or None,
            "sync_action": sync_action or None,
            "degraded": degraded
        }

    members = list(
        raid.get(
            "physical_members",
            []
        )
        or []
    )

    if not members:
        return {
            "success": False,
            "reason": "raid_no_members"
        }

    checked_members = []

    for device in members:

        device_path = known_devices.get(
            device
        )

        if device_path is None:
            return {
                "success": False,
                "reason": "raid_member_not_found",
                "device": device
            }

        disk_type = get_disk_type(
            device,
            device_path
        )

        # Avoid partial power-state changes in mixed SSD/HDD arrays. This
        # group action is intentionally offered only for all-HDD md arrays.
        if disk_type != "HDD":
            return {
                "success": False,
                "reason": "raid_not_all_hdd",
                "device": device,
                "type": disk_type
            }

        cached_access = (
            get_current_process_access(
                device
            )
        )

        if cached_access:
            return {
                "success": False,
                "reason": "raid_busy_process",
                "device": device
            }

        immediate_io = disk_has_immediate_io(
            device_path
        )

        if immediate_io is True:
            return {
                "success": False,
                "reason": "raid_busy_io",
                "device": device
            }

        if (
            immediate_io is None
            and disk_activity.get(
                device,
                {}
            ).get(
                "status"
            ) == "ACTIVE"
        ):
            return {
                "success": False,
                "reason": "raid_activity_unknown",
                "device": device
            }

        checked_members.append(
            (
                device,
                device_path
            )
        )

    return {
        "success": True,
        "array_state": array_state,
        "sync_action": sync_action,
        "degraded": degraded,
        "members": checked_members
    }


@app.post("/api/raid/{raid_device}/standby")
def standby_raid_now(
    raid_device: str,
    request: Request
):

    require_auth(
        request
    )

    known_devices = {
        name: path
        for name, path in get_devices()
    }

    raid_topology = get_raid_topology(
        get_mounts()
    )

    raid = raid_topology.get(
        raid_device
    )

    if not raid:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "raid_not_found"
            }
        )

    precheck = get_raid_manual_standby_precheck(
        raid_device,
        raid,
        known_devices
    )

    if not precheck.get(
        "success"
    ):
        raise HTTPException(
            status_code=409,
            detail=precheck
        )

    results = []

    for device, device_path in precheck.get(
        "members",
        []
    ):

        # put_hdd_in_standby() repeats the per-disk activity checks directly
        # before issuing the command, reducing the race window after precheck.
        result = put_hdd_in_standby(
            device,
            device_path
        )

        member_result = {
            "device": device,
            **result
        }

        results.append(
            member_result
        )

        if not result.get(
            "success"
        ):
            reason = result.get(
                "reason",
                "standby_failed"
            )

            status_code = (
                409
                if reason in (
                    "busy_process",
                    "busy_io",
                    "activity_unknown"
                )
                else 503
            )

            raise HTTPException(
                status_code=status_code,
                detail={
                    "reason": "raid_member_standby_failed",
                    "failed_device": device,
                    "member_reason": reason,
                    "results": results
                }
            )

    return {
        "success": True,
        "raid_device": raid_device,
        "array_state": precheck.get(
            "array_state"
        ),
        "sync_action": precheck.get(
            "sync_action"
        ),
        "degraded": precheck.get(
            "degraded"
        ),
        "members": results
    }


@app.post("/api/disks/{device}/standby")
def standby_disk_now(
    device: str,
    request: Request
):

    require_auth(
        request
    )

    known_devices = {
        name: path
        for name, path in get_devices()
    }

    if device not in known_devices:

        raise HTTPException(
            status_code=404,
            detail={
                "reason": "not_found"
            }
        )

    device_path = known_devices[
        device
    ]

    disk_type = get_disk_type(
        device,
        device_path
    )

    if disk_type != "HDD":

        raise HTTPException(
            status_code=400,
            detail={
                "reason": "not_hdd"
            }
        )

    mounts = get_mounts()

    raid_topology = get_raid_topology(
        mounts
    )

    raid_memberships = (
        get_raid_memberships_for_device(
            device,
            raid_topology
        )
    )

    if raid_memberships:

        raise HTTPException(
            status_code=409,
            detail={
                "reason": "raid_member"
            }
        )

    result = put_hdd_in_standby(
        device,
        device_path
    )

    if not result.get(
        "success"
    ):

        reason = result.get(
            "reason",
            "standby_failed"
        )

        status_code = (
            409
            if reason in (
                "busy_process",
                "busy_io",
                "activity_unknown"
            )
            else 503
        )

        raise HTTPException(
            status_code=status_code,
            detail=result
        )

    return {
        "success": True,
        "device": device,
        **result
    }



def get_smart_full_check_state():

    with SMART_FULL_CHECK_LOCK:
        return json.loads(
            json.dumps(
                SMART_FULL_CHECK_STATE
            )
        )


def update_smart_full_check_state(
    **values
):

    with SMART_FULL_CHECK_LOCK:
        SMART_FULL_CHECK_STATE.update(
            values
        )


def smart_full_check_worker():

    devices = get_devices()

    update_smart_full_check_state(
        running=True,
        started_at=datetime.now(
            timezone.utc
        ).isoformat(),
        finished_at=None,
        total=len(devices),
        completed=0,
        percent=0,
        current_device=None,
        results=[],
        error=None
    )

    results = []

    try:

        for index, (
            device,
            device_path
        ) in enumerate(
            devices,
            start=1
        ):

            update_smart_full_check_state(
                current_device=device
            )

            disk_type = get_disk_type(
                device,
                device_path
            )

            previous = dict(
                smart_cache.get(
                    device,
                    {}
                )
            )

            wake = None
            error = None
            smart = None

            try:

                if disk_type == "HDD":

                    # This global check is an explicit user action.
                    # Waking sleeping HDDs is intentional here.
                    wake = wake_disk_for_smart(
                        device
                    )

                    manual_awake_until[
                        device
                    ] = time.time() + 90

                smart = read_smart_now(
                    device,
                    "full-check"
                )

            except Exception as exc:

                error = str(
                    exc
                )

            changes = []

            if isinstance(
                smart,
                dict
            ):

                fields_to_compare = list(
                    SMART_HISTORY_FIELDS
                ) + [
                    "health",
                    "critical_warning"
                ]

                for field in fields_to_compare:

                    before = previous.get(
                        field
                    )

                    after = smart.get(
                        field
                    )

                    if (
                        before is not None
                        and after is not None
                        and before != after
                    ):

                        changes.append(
                            {
                                "field": field,
                                "before": before,
                                "after": after
                            }
                        )

            result = {
                "device": device,
                "type": disk_type,
                "success": (
                    isinstance(
                        smart,
                        dict
                    )
                    and (
                        smart.get(
                            "available"
                        )
                        or any(
                            smart.get(
                                field
                            )
                            is not None
                            for field
                            in SMART_HISTORY_FIELDS
                        )
                    )
                ),
                "health": (
                    smart.get(
                        "health"
                    )
                    if isinstance(
                        smart,
                        dict
                    )
                    else None
                ),
                "changes": changes,
                "wake": wake,
                "error": error
            }

            results.append(
                result
            )

            percent = (
                round(
                    (
                        index
                        / len(
                            devices
                        )
                    )
                    * 100
                )
                if devices
                else 100
            )

            update_smart_full_check_state(
                completed=index,
                percent=percent,
                results=list(
                    results
                )
            )

        update_smart_full_check_state(
            running=False,
            finished_at=datetime.now(
                timezone.utc
            ).isoformat(),
            current_device=None,
            percent=100
        )

        save_smart_full_check_state()

    except Exception as exc:

        update_smart_full_check_state(
            running=False,
            finished_at=datetime.now(
                timezone.utc
            ).isoformat(),
            current_device=None,
            error=str(
                exc
            )
        )


@app.post("/api/smart/full-check")
def start_smart_full_check(
    request: Request
):

    require_auth(
        request
    )

    with SMART_FULL_CHECK_LOCK:

        if SMART_FULL_CHECK_STATE.get(
            "running"
        ):

            return {
                "success": True,
                "already_running": True,
                "state": json.loads(
                    json.dumps(
                        SMART_FULL_CHECK_STATE
                    )
                )
            }

        SMART_FULL_CHECK_STATE.update(
            {
                "running": True,
                "started_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "finished_at": None,
                "total": 0,
                "completed": 0,
                "percent": 0,
                "current_device": None,
                "results": [],
                "error": None
            }
        )

    thread = threading.Thread(
        target=smart_full_check_worker,
        name="disk-monitor-smart-full-check",
        daemon=True
    )

    thread.start()

    return {
        "success": True,
        "already_running": False,
        "state": get_smart_full_check_state()
    }


@app.get("/api/smart/full-check")
def smart_full_check_status(
    request: Request
):

    require_auth(
        request
    )

    return get_smart_full_check_state()


@app.post("/api/disks/{device}/smart/refresh")
def refresh_disk_smart(
    device: str,
    request: Request
):

    require_auth(
        request
    )

    known_devices = {
        name: path
        for name, path in get_devices()
    }

    if device not in known_devices:

        raise HTTPException(
            status_code=404,
            detail="Disk not found"
        )

    device_path = known_devices[
        device
    ]

    disk_type = get_disk_type(
        device,
        device_path
    )

    wake = None

    if disk_type == "HDD":

        # Manual action: try to wake the drive first. Do NOT abort only
        # because the controller/ZimaOS power-state check still reports
        # standby. Some USB bridges and some local-storage state reports are
        # delayed or unreliable. The subsequent SMART read is the decisive
        # test and may itself complete the wake-up.
        wake = wake_disk_for_smart(
            device
        )

        manual_awake_until[
            device
        ] = time.time() + 60

    smart = read_smart_now(
        device,
        "manual-refresh"
    )

    has_real_smart_data = (
        isinstance(
            smart,
            dict
        )
        and (
            smart.get(
                "available"
            )
            or any(
                smart.get(
                    field
                )
                is not None
                for field in SMART_HISTORY_FIELDS
            )
            or smart.get(
                "serial_number"
            )
            is not None
            or smart.get(
                "firmware_version"
            )
            is not None
        )
    )

    if not has_real_smart_data:

        raise HTTPException(
            status_code=503,
            detail={
                "message": (
                    "The manual SMART read did not return usable data."
                ),
                "device": device,
                "wake": wake,
                "smart": smart
            }
        )

    # If SMART succeeded, the manual request reached the drive regardless of
    # whether the separate power-state verifier had already caught up.
    if disk_type == "HDD":

        transport = get_device_transport(
            device,
            device_path
        )

        now_utc = datetime.now(
            timezone.utc
        ).isoformat()

        activity = disk_activity.get(
            device
        )

        if isinstance(
            activity,
            dict
        ):

            activity[
                "idle_since"
            ] = now_utc

            activity[
                "last_activity"
            ] = now_utc

            save_disk_activity_state(
                force=True
            )

        if transport == "usb":

            model = read_file(
                device_path / "device/model"
            )

            vendor = read_file(
                device_path / "device/vendor"
            )

            size_bytes = get_size(
                device_path
            )

            serial = (
                smart.get(
                    "serial_number"
                )
                or read_file(
                    device_path / "device/serial"
                )
            )

            stable_id = get_disk_stable_id(
                device,
                device_path,
                model=model,
                vendor=vendor,
                serial=serial,
                size_bytes=size_bytes
            )

            usb_config = get_usb_standby_config(
                stable_id
            )

            expected_minutes = usb_config.get(
                "minutes"
            )

            hold_seconds = (
                max(
                    60,
                    int(
                        expected_minutes
                    ) * 60
                )
                if expected_minutes
                else 60
            )

            manual_awake_until[
                device
            ] = time.time() + hold_seconds

            set_usb_runtime_power_state(
                device,
                "ACTIVE",
                "manual-smart-read"
            )

        else:

            manual_awake_until[
                device
            ] = time.time() + 90

    return {
        "success": True,
        "device": device,
        "wake": wake,
        "smart": smart
    }


@app.get("/api/disks/{device}/smart/history")
def disk_smart_history(
    device: str,
    request: Request,
    range: str = "7d"
):

    require_auth(
        request
    )

    if range not in (
        "24h",
        "7d",
        "30d",
        "1y"
    ):

        raise HTTPException(
            status_code=400,
            detail="Invalid SMART history range"
        )

    history = get_smart_history(
        device,
        range
    )

    if history is None:

        raise HTTPException(
            status_code=404,
            detail="Disk not found"
        )

    return history


@app.get("/api/status")
def status(
    request: Request
):

    require_auth(
        request
    )

    return {
        "service": "Disk Monitor",
        "version": "0.22.14",
        "status": "running",
        "release_credentials_required": True,
        "login_rate_limit": True,
        "api_docs_enabled": False,
        "session_https_only": SESSION_HTTPS_ONLY,
        "monitor_interval_seconds": INTERVAL,
        "process_access_monitor": (
            HOST_PROC.exists()
        ),
        "process_access_ttl_seconds": PROCESS_ACCESS_TTL,
        "process_access_disk_io_hold_seconds":
            PROCESS_ACCESS_DISK_IO_HOLD_SECONDS,
        "raid_detection": True,
        "resource_monitor": True,
        "flash_smart_detection": True,
        "manual_hdd_standby": True,
        "raid_manual_standby": True,
        "raid_manual_standby_requires_clean_idle": True,
        "usb_hdd_standby_fallback": True,
        "usb_hdd_smartctl_power_state": True,
        "usb_hdd_recent_io_active": True,
        "usb_hdd_event_driven_power_state": True,
        "usb_hdd_periodic_power_poll": False,
        "usb_hdd_initial_power_probe": False,
        "usb_hdd_passive_idle_state": True,
        "usb_hdd_estimated_standby": True,
        "usb_hdd_per_drive_timer_config": True,
        "usb_hdd_no_hdparm_fallback": True,
        "storage_usage_cached": True,
        "storage_usage_refresh_seconds":
            STORAGE_USAGE_REFRESH_SECONDS,
        "storage_usage_uses_statvfs": True,
        "storage_usage_no_wake_policy": True,
        "automatic_hdd_power_probes": False,
        "automatic_hdd_smart_reads": False,
        "smart_history": True,
        "smart_history_database": "sqlite",
        "smart_history_retention_days":
            SMART_HISTORY_RETENTION_DAYS,
        "smart_history_safe_ssd_interval_seconds":
            SMART_HISTORY_SAFE_INTERVAL_SECONDS,
        "smart_history_automatic_hdd_reads": False,
        "smart_history_usb_partial_smart_values": True,
        "manual_smart_read_uses_smart_as_authority": True,
        "manual_smart_wake_verification_is_nonblocking": True,
        "manual_smart_state_overrides_stale_standby": True,
        "usb_smart_tries_all_device_modes": True,
        "usb_smart_prefers_full_ata_table": True,
        "advanced_ata_smart_attributes": True,
        "rotation_rate": True,
        "smart_full_check": True,
        "smart_full_check_wakes_hdds": True,
        "smart_full_check_live_progress": True,
        "smart_full_check_persistent_last_result": True,
        "smart_full_check_state_file":
            str(
                SMART_FULL_CHECK_STATE_FILE
            ),
        "storage_usage_deduplicated": True,
        "storage_usage_identity":
            "host-mountinfo-major-minor",
        "raid_display_metadata": True,
        "service_runtime":
            get_service_runtime(),
        "zimaos_standby_api": True,
        "zimaos_local_storage_url": (
            discover_zimaos_local_storage()
        )
    }