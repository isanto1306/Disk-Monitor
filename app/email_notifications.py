import asyncio
import json
import os
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel


CONFIG_FILE = Path("/app/cache/email_notifications.json")
STATE_FILE = Path("/app/cache/email_notification_state.json")
FRONTEND_FILE = Path("/app/static/email-notifications.js")

POLL_SECONDS = 60
STARTUP_GRACE_SECONDS = 90
MISSING_CONFIRM_POLLS = 3
SUPPORTED_LANGUAGES = {"auto", "de", "en", "fr", "pt", "es"}
SUPPORTED_ENCRYPTION = {"starttls", "ssl_tls", "none"}

CONFIG_LOCK = threading.RLock()
STATE_LOCK = threading.RLock()
MAIN = None
INSTALLED = False


def _default_config():
    return {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "encryption": "starttls",
        "username": "",
        "password": "",
        "sender": "",
        "recipient": "",
        "language": "auto",
        "last_ui_language": "en",
        "temperature_threshold_c": 55,
        "notify_smart_health": True,
        "notify_smart_attributes": True,
        "notify_missing_drive": True,
        "notify_raid": True,
        "notify_temperature": True,
        "notify_recovery": True,
    }


def _default_state():
    return {
        "known_disks": {},
        "missing_counts": {},
        "active_alerts": {},
        "last_success_at": None,
        "last_error": None,
        "last_error_at": None,
        "last_monitor_at": None,
    }


def _read_json(path: Path, default):
    try:
        if not path.exists():
            return default()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return default()
        return data
    except Exception:
        return default()


def _write_json(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        os.chmod(temp, 0o600)
    except Exception:
        pass
    temp.replace(path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass


CONFIG = _default_config()
CONFIG.update(_read_json(CONFIG_FILE, _default_config))
STATE = _default_state()
STATE.update(_read_json(STATE_FILE, _default_state))


class EmailSettingsPayload(BaseModel):
    enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    encryption: str = "starttls"
    username: str = ""
    password: str | None = None
    sender: str = ""
    recipient: str = ""
    language: str = "auto"
    temperature_threshold_c: int = 55
    notify_smart_health: bool = True
    notify_smart_attributes: bool = True
    notify_missing_drive: bool = True
    notify_raid: bool = True
    notify_temperature: bool = True
    notify_recovery: bool = True


class UiLanguagePayload(BaseModel):
    language: str


def _clean_config(raw: dict, preserve_password: str = ""):
    cfg = _default_config()

    cfg["enabled"] = bool(raw.get("enabled", False))
    cfg["smtp_host"] = str(raw.get("smtp_host") or "").strip()

    try:
        port = int(raw.get("smtp_port", 587))
    except Exception:
        port = 587
    if not 1 <= port <= 65535:
        raise HTTPException(status_code=400, detail="invalid_smtp_port")
    cfg["smtp_port"] = port

    encryption = str(raw.get("encryption") or "starttls").strip().lower()
    if encryption not in SUPPORTED_ENCRYPTION:
        raise HTTPException(status_code=400, detail="invalid_encryption")
    cfg["encryption"] = encryption

    cfg["username"] = str(raw.get("username") or "").strip()
    supplied_password = raw.get("password")
    cfg["password"] = (
        str(supplied_password)
        if supplied_password not in (None, "")
        else preserve_password
    )
    cfg["sender"] = str(raw.get("sender") or "").strip()
    cfg["recipient"] = str(raw.get("recipient") or "").strip()

    language = str(raw.get("language") or "auto").strip().lower()
    if language not in SUPPORTED_LANGUAGES:
        raise HTTPException(status_code=400, detail="invalid_language")
    cfg["language"] = language

    ui_language = str(raw.get("last_ui_language") or "en").strip().lower()
    cfg["last_ui_language"] = ui_language if ui_language in SUPPORTED_LANGUAGES - {"auto"} else "en"

    try:
        threshold = int(raw.get("temperature_threshold_c", 55))
    except Exception:
        threshold = 55
    if not 35 <= threshold <= 90:
        raise HTTPException(status_code=400, detail="invalid_temperature_threshold")
    cfg["temperature_threshold_c"] = threshold

    for key in (
        "notify_smart_health",
        "notify_smart_attributes",
        "notify_missing_drive",
        "notify_raid",
        "notify_temperature",
        "notify_recovery",
    ):
        cfg[key] = bool(raw.get(key, True))

    if cfg["enabled"]:
        _validate_sendable(cfg)

    return cfg


def _validate_sendable(cfg: dict):
    missing = []
    if not cfg.get("smtp_host"):
        missing.append("smtp_host")
    if not cfg.get("sender"):
        missing.append("sender")
    if not cfg.get("recipient"):
        missing.append("recipient")
    if missing:
        raise HTTPException(
            status_code=400,
            detail={"reason": "incomplete_email_settings", "fields": missing},
        )


def _public_config():
    with CONFIG_LOCK:
        cfg = dict(CONFIG)
    password_set = bool(cfg.pop("password", ""))
    configured = bool(
        cfg.get("smtp_host")
        and cfg.get("sender")
        and cfg.get("recipient")
    )
    with STATE_LOCK:
        runtime = {
            "last_success_at": STATE.get("last_success_at"),
            "last_error": STATE.get("last_error"),
            "last_error_at": STATE.get("last_error_at"),
            "last_monitor_at": STATE.get("last_monitor_at"),
        }
    return {
        **cfg,
        "password_set": password_set,
        "configured": configured,
        **runtime,
    }


def _save_config():
    with CONFIG_LOCK:
        _write_json(CONFIG_FILE, dict(CONFIG))


def _save_state():
    with STATE_LOCK:
        _write_json(STATE_FILE, dict(STATE))


def _resolve_language(cfg: dict):
    selected = str(cfg.get("language") or "auto").lower()
    if selected == "auto":
        selected = str(cfg.get("last_ui_language") or "en").lower()
    return selected if selected in SUPPORTED_LANGUAGES - {"auto"} else "en"


TEXT = {
    "en": {
        "test_subject": "Disk Monitor test email",
        "test_body": "Disk Monitor email notifications are configured correctly.",
        "alert_prefix": "Disk Monitor alert",
        "recovery_prefix": "Disk Monitor recovery",
        "event_smart": "SMART",
        "event_temperature": "Temperature",
        "event_raid": "RAID",
        "event_drive": "Drive",
        "drive": "Drive",
        "model": "Model",
        "issue": "Issue",
        "time": "Time",
        "check": "Please check the drive and its connection.",
        "smart_health": "SMART health changed to {value}.",
        "smart_value": "{field} changed from {before} to {after}.",
        "missing": "The drive is no longer detected.",
        "returned": "The drive is detected again.",
        "raid": "RAID {raid} reports degraded={degraded}, state={state}.",
        "raid_ok": "RAID {raid} is healthy again.",
        "temperature": "Temperature reached {value} °C (limit {limit} °C).",
        "temperature_ok": "Temperature returned to {value} °C.",
        "health_ok": "SMART health returned to {value}.",
    },
    "de": {
        "test_subject": "Disk Monitor Test E Mail",
        "test_body": "Die E Mail Benachrichtigungen von Disk Monitor sind korrekt eingerichtet.",
        "alert_prefix": "Disk Monitor Warnung",
        "recovery_prefix": "Disk Monitor Entwarnung",
        "event_smart": "SMART",
        "event_temperature": "Temperatur",
        "event_raid": "RAID",
        "event_drive": "Laufwerk",
        "drive": "Laufwerk",
        "model": "Modell",
        "issue": "Problem",
        "time": "Zeitpunkt",
        "check": "Bitte überprüfe das Laufwerk und seine Verbindung.",
        "smart_health": "Der SMART Zustand hat sich auf {value} geändert.",
        "smart_value": "{field} hat sich von {before} auf {after} geändert.",
        "missing": "Das Laufwerk wird nicht mehr erkannt.",
        "returned": "Das Laufwerk wird wieder erkannt.",
        "raid": "RAID {raid} meldet degraded={degraded}, Status={state}.",
        "raid_ok": "RAID {raid} ist wieder fehlerfrei.",
        "temperature": "Die Temperatur hat {value} °C erreicht (Grenze {limit} °C).",
        "temperature_ok": "Die Temperatur ist wieder auf {value} °C gesunken.",
        "health_ok": "Der SMART Zustand ist wieder {value}.",
    },
    "fr": {
        "test_subject": "E mail de test Disk Monitor",
        "test_body": "Les notifications e mail de Disk Monitor sont correctement configurées.",
        "alert_prefix": "Alerte Disk Monitor",
        "recovery_prefix": "Retour à la normale Disk Monitor",
        "event_smart": "SMART",
        "event_temperature": "Température",
        "event_raid": "RAID",
        "event_drive": "Disque",
        "drive": "Disque",
        "model": "Modèle",
        "issue": "Problème",
        "time": "Heure",
        "check": "Veuillez vérifier le disque et sa connexion.",
        "smart_health": "L’état SMART est passé à {value}.",
        "smart_value": "{field} est passé de {before} à {after}.",
        "missing": "Le disque n’est plus détecté.",
        "returned": "Le disque est de nouveau détecté.",
        "raid": "Le RAID {raid} signale degraded={degraded}, état={state}.",
        "raid_ok": "Le RAID {raid} est de nouveau sain.",
        "temperature": "La température a atteint {value} °C (limite {limit} °C).",
        "temperature_ok": "La température est revenue à {value} °C.",
        "health_ok": "L’état SMART est revenu à {value}.",
    },
    "pt": {
        "test_subject": "E mail de teste do Disk Monitor",
        "test_body": "As notificações por e mail do Disk Monitor estão configuradas corretamente.",
        "alert_prefix": "Alerta do Disk Monitor",
        "recovery_prefix": "Normalização do Disk Monitor",
        "event_smart": "SMART",
        "event_temperature": "Temperatura",
        "event_raid": "RAID",
        "event_drive": "Unidade",
        "drive": "Unidade",
        "model": "Modelo",
        "issue": "Problema",
        "time": "Hora",
        "check": "Verifique a unidade e a respetiva ligação.",
        "smart_health": "O estado SMART mudou para {value}.",
        "smart_value": "{field} mudou de {before} para {after}.",
        "missing": "A unidade deixou de ser detetada.",
        "returned": "A unidade voltou a ser detetada.",
        "raid": "O RAID {raid} indica degraded={degraded}, estado={state}.",
        "raid_ok": "O RAID {raid} voltou ao estado normal.",
        "temperature": "A temperatura atingiu {value} °C (limite {limit} °C).",
        "temperature_ok": "A temperatura voltou a {value} °C.",
        "health_ok": "O estado SMART voltou a {value}.",
    },
    "es": {
        "test_subject": "Correo de prueba de Disk Monitor",
        "test_body": "Las notificaciones por correo de Disk Monitor están configuradas correctamente.",
        "alert_prefix": "Alerta de Disk Monitor",
        "recovery_prefix": "Recuperación de Disk Monitor",
        "event_smart": "SMART",
        "event_temperature": "Temperatura",
        "event_raid": "RAID",
        "event_drive": "Unidad",
        "drive": "Unidad",
        "model": "Modelo",
        "issue": "Problema",
        "time": "Hora",
        "check": "Comprueba la unidad y su conexión.",
        "smart_health": "El estado SMART cambió a {value}.",
        "smart_value": "{field} cambió de {before} a {after}.",
        "missing": "La unidad ya no se detecta.",
        "returned": "La unidad vuelve a detectarse.",
        "raid": "El RAID {raid} informa degraded={degraded}, estado={state}.",
        "raid_ok": "El RAID {raid} vuelve a estar correcto.",
        "temperature": "La temperatura alcanzó {value} °C (límite {limit} °C).",
        "temperature_ok": "La temperatura volvió a {value} °C.",
        "health_ok": "El estado SMART volvió a {value}.",
    },
}

FIELD_LABELS = {
    "en": {
        "reallocated_sectors": "Reallocated sectors",
        "pending_sectors": "Pending sectors",
        "offline_uncorrectable": "Offline uncorrectable sectors",
        "reported_uncorrectable": "Reported uncorrectable errors",
        "crc_errors": "CRC errors",
        "media_errors": "Media errors",
        "critical_warning": "NVMe critical warning",
        "error_information_log_entries": "NVMe error log entries",
    },
    "de": {
        "reallocated_sectors": "Neu zugewiesene Sektoren",
        "pending_sectors": "Ausstehende Sektoren",
        "offline_uncorrectable": "Nicht korrigierbare Offline Sektoren",
        "reported_uncorrectable": "Gemeldete nicht korrigierbare Fehler",
        "crc_errors": "CRC Fehler",
        "media_errors": "Medienfehler",
        "critical_warning": "NVMe kritische Warnung",
        "error_information_log_entries": "NVMe Fehlerprotokoll Einträge",
    },
    "fr": {
        "reallocated_sectors": "Secteurs réalloués",
        "pending_sectors": "Secteurs en attente",
        "offline_uncorrectable": "Secteurs hors ligne non corrigibles",
        "reported_uncorrectable": "Erreurs non corrigibles signalées",
        "crc_errors": "Erreurs CRC",
        "media_errors": "Erreurs de média",
        "critical_warning": "Avertissement critique NVMe",
        "error_information_log_entries": "Entrées du journal d’erreurs NVMe",
    },
    "pt": {
        "reallocated_sectors": "Setores realocados",
        "pending_sectors": "Setores pendentes",
        "offline_uncorrectable": "Setores offline não corrigíveis",
        "reported_uncorrectable": "Erros não corrigíveis comunicados",
        "crc_errors": "Erros CRC",
        "media_errors": "Erros de suporte",
        "critical_warning": "Aviso crítico NVMe",
        "error_information_log_entries": "Entradas do registo de erros NVMe",
    },
    "es": {
        "reallocated_sectors": "Sectores reasignados",
        "pending_sectors": "Sectores pendientes",
        "offline_uncorrectable": "Sectores sin conexión no corregibles",
        "reported_uncorrectable": "Errores no corregibles notificados",
        "crc_errors": "Errores CRC",
        "media_errors": "Errores de medios",
        "critical_warning": "Advertencia crítica NVMe",
        "error_information_log_entries": "Entradas del registro de errores NVMe",
    },
}


def _tr(lang, key):
    return TEXT.get(lang, TEXT["en"]).get(key, TEXT["en"].get(key, key))


def _field_label(lang, field):
    return FIELD_LABELS.get(lang, {}).get(field) or FIELD_LABELS["en"].get(field) or field.replace("_", " ")


def _smtp_send(cfg: dict, subject: str, body: str):
    _validate_sendable(cfg)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = cfg["sender"]
    message["To"] = cfg["recipient"]
    message.set_content(body)

    host = cfg["smtp_host"]
    port = int(cfg["smtp_port"])
    encryption = cfg["encryption"]

    if encryption == "ssl_tls":
        client = smtplib.SMTP_SSL(
            host,
            port,
            timeout=15,
            context=ssl.create_default_context(),
        )
    else:
        client = smtplib.SMTP(host, port, timeout=15)

    try:
        client.ehlo()
        if encryption == "starttls":
            client.starttls(context=ssl.create_default_context())
            client.ehlo()
        if cfg.get("username"):
            client.login(cfg["username"], cfg.get("password") or "")
        client.send_message(message)
    finally:
        try:
            client.quit()
        except Exception:
            try:
                client.close()
            except Exception:
                pass


def _record_send_success():
    with STATE_LOCK:
        STATE["last_success_at"] = datetime.now(timezone.utc).isoformat()
        STATE["last_error"] = None
        STATE["last_error_at"] = None
        _write_json(STATE_FILE, dict(STATE))


def _record_send_error(exc):
    with STATE_LOCK:
        STATE["last_error"] = str(exc)[:500]
        STATE["last_error_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(STATE_FILE, dict(STATE))


def _format_notification(cfg, title, issue, disk=None, recovery=False):
    lang = _resolve_language(cfg)
    prefix = _tr(lang, "recovery_prefix" if recovery else "alert_prefix")
    subject = f"{prefix}: {title}"
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = []
    if disk:
        lines.append(f"{_tr(lang, 'drive')}: /dev/{disk.get('device', '-')}" )
        if disk.get("model"):
            lines.append(f"{_tr(lang, 'model')}: {disk.get('model')}")
    lines.append(f"{_tr(lang, 'issue')}: {issue}")
    lines.append(f"{_tr(lang, 'time')}: {now}")
    if not recovery:
        lines.extend(["", _tr(lang, "check")])
    return subject, "\n".join(lines)


def _send_event(cfg, title, issue, disk=None, recovery=False):
    subject, body = _format_notification(cfg, title, issue, disk, recovery)
    try:
        _smtp_send(cfg, subject, body)
        _record_send_success()
        return True
    except Exception as exc:
        _record_send_error(exc)
        return False


def _disk_key(disk):
    return str(
        disk.get("stable_id")
        or disk.get("serial")
        or disk.get("device")
        or ""
    ).strip()


def _number(value):
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _snapshot(disk):
    smart = disk.get("smart") if isinstance(disk.get("smart"), dict) else {}
    raids = []
    for raid in disk.get("raid_memberships") or []:
        if not isinstance(raid, dict):
            continue
        raids.append({
            "device": raid.get("device"),
            "state": raid.get("state"),
            "degraded": raid.get("degraded"),
        })
    return {
        "device": disk.get("device"),
        "model": disk.get("model"),
        "stable_id": disk.get("stable_id"),
        "health": smart.get("health"),
        "temperature_celsius": smart.get("temperature_celsius"),
        "reallocated_sectors": smart.get("reallocated_sectors"),
        "pending_sectors": smart.get("pending_sectors"),
        "offline_uncorrectable": smart.get("offline_uncorrectable"),
        "reported_uncorrectable": smart.get("reported_uncorrectable"),
        "crc_errors": smart.get("crc_errors"),
        "media_errors": smart.get("media_errors"),
        "critical_warning": smart.get("critical_warning"),
        "error_information_log_entries": smart.get("error_information_log_entries"),
        "raid_memberships": raids,
    }


def _alert_is_active(key):
    return bool(STATE.setdefault("active_alerts", {}).get(key))


def _set_alert(key, value=True):
    STATE.setdefault("active_alerts", {})[key] = value


def _clear_alert(key):
    STATE.setdefault("active_alerts", {}).pop(key, None)


def _evaluate_disk(cfg, disk, previous):
    lang = _resolve_language(cfg)
    key = _disk_key(disk)
    if not key:
        return
    current = _snapshot(disk)

    health = str(current.get("health") or "").upper()
    health_key = f"health:{key}"
    if cfg.get("notify_smart_health") and health in {"FAILED", "WARNING"}:
        if not _alert_is_active(health_key):
            issue = _tr(lang, "smart_health").format(value=health)
            if _send_event(cfg, _tr(lang, "event_smart"), issue, disk):
                _set_alert(health_key, health)
    elif _alert_is_active(health_key) and health in {"PASSED", "OK"}:
        if cfg.get("notify_recovery"):
            issue = _tr(lang, "health_ok").format(value=health)
            if _send_event(cfg, _tr(lang, "event_smart"), issue, disk, recovery=True):
                _clear_alert(health_key)
        else:
            _clear_alert(health_key)

    if cfg.get("notify_smart_attributes"):
        for field in (
            "reallocated_sectors",
            "pending_sectors",
            "offline_uncorrectable",
            "reported_uncorrectable",
            "crc_errors",
            "media_errors",
            "critical_warning",
            "error_information_log_entries",
        ):
            after = _number(current.get(field))
            before = _number(previous.get(field)) if previous else None
            if after is None or after <= 0:
                continue
            if before is not None and after <= before:
                continue
            alert_key = f"smart:{field}:{key}:{after}"
            if _alert_is_active(alert_key):
                continue
            issue = _tr(lang, "smart_value").format(
                field=_field_label(lang, field),
                before=(before if before is not None else 0),
                after=after,
            )
            if _send_event(cfg, _tr(lang, "event_smart"), issue, disk):
                _set_alert(alert_key, True)

    if cfg.get("notify_temperature"):
        temp = _number(current.get("temperature_celsius"))
        limit = int(cfg.get("temperature_threshold_c") or 55)
        temp_key = f"temperature:{key}"
        if temp is not None and temp >= limit:
            if not _alert_is_active(temp_key):
                issue = _tr(lang, "temperature").format(value=temp, limit=limit)
                if _send_event(cfg, _tr(lang, "event_temperature"), issue, disk):
                    _set_alert(temp_key, temp)
        elif _alert_is_active(temp_key) and temp is not None and temp <= limit - 3:
            if cfg.get("notify_recovery"):
                issue = _tr(lang, "temperature_ok").format(value=temp)
                if _send_event(cfg, _tr(lang, "event_temperature"), issue, disk, recovery=True):
                    _clear_alert(temp_key)
            else:
                _clear_alert(temp_key)

    if cfg.get("notify_raid"):
        current_raids = {
            str(r.get("device") or ""): r
            for r in current.get("raid_memberships") or []
            if r.get("device")
        }
        for raid_name, raid in current_raids.items():
            degraded = _number(raid.get("degraded"))
            state = str(raid.get("state") or "unknown")
            bad_state = state.lower() in {"inactive", "clear", "broken", "suspended"}
            raid_key = f"raid:{raid_name}"
            if (degraded is not None and degraded > 0) or bad_state:
                if not _alert_is_active(raid_key):
                    issue = _tr(lang, "raid").format(
                        raid=raid_name,
                        degraded=(degraded if degraded is not None else "?"),
                        state=state,
                    )
                    if _send_event(cfg, _tr(lang, "event_raid"), issue, disk):
                        _set_alert(raid_key, True)
            elif _alert_is_active(raid_key):
                if cfg.get("notify_recovery"):
                    issue = _tr(lang, "raid_ok").format(raid=raid_name)
                    if _send_event(cfg, _tr(lang, "event_raid"), issue, disk, recovery=True):
                        _clear_alert(raid_key)
                else:
                    _clear_alert(raid_key)


def _monitor_once(disks):
    with CONFIG_LOCK:
        cfg = dict(CONFIG)
    if not cfg.get("enabled"):
        return
    try:
        _validate_sendable(cfg)
    except HTTPException:
        return

    current = {}
    for disk in disks:
        if not isinstance(disk, dict):
            continue
        key = _disk_key(disk)
        if key:
            current[key] = disk

    with STATE_LOCK:
        known = STATE.setdefault("known_disks", {})
        missing_counts = STATE.setdefault("missing_counts", {})

        # First run creates a baseline without sending a burst of historical alerts.
        if not known:
            for key, disk in current.items():
                known[key] = _snapshot(disk)
            STATE["last_monitor_at"] = datetime.now(timezone.utc).isoformat()
            _write_json(STATE_FILE, dict(STATE))
            return

        for key, disk in current.items():
            previous = known.get(key) if isinstance(known.get(key), dict) else {}
            missing_key = f"missing:{key}"

            if _alert_is_active(missing_key):
                if cfg.get("notify_recovery"):
                    lang = _resolve_language(cfg)
                    if _send_event(cfg, _tr(lang, "event_drive"), _tr(lang, "returned"), disk, recovery=True):
                        _clear_alert(missing_key)
                else:
                    _clear_alert(missing_key)

            missing_counts.pop(key, None)
            _evaluate_disk(cfg, disk, previous)
            known[key] = _snapshot(disk)

        if cfg.get("notify_missing_drive"):
            for key, previous in list(known.items()):
                if key in current:
                    continue
                count = int(missing_counts.get(key, 0) or 0) + 1
                missing_counts[key] = count
                missing_key = f"missing:{key}"
                if count >= MISSING_CONFIRM_POLLS and not _alert_is_active(missing_key):
                    disk = {
                        "device": previous.get("device", "-"),
                        "model": previous.get("model"),
                    }
                    lang = _resolve_language(cfg)
                    if _send_event(cfg, _tr(lang, "event_drive"), _tr(lang, "missing"), disk):
                        _set_alert(missing_key, True)

        STATE["last_monitor_at"] = datetime.now(timezone.utc).isoformat()
        _write_json(STATE_FILE, dict(STATE))


async def _monitor_loop():
    await asyncio.sleep(STARTUP_GRACE_SECONDS)
    while True:
        try:
            with CONFIG_LOCK:
                enabled = bool(CONFIG.get("enabled"))
            if enabled and MAIN is not None:
                disks = await asyncio.to_thread(MAIN.get_disks)
                await asyncio.to_thread(_monitor_once, disks)
        except Exception as exc:
            _record_send_error(exc)
        await asyncio.sleep(POLL_SECONDS)


router = APIRouter()


@router.get("/email-notifications.js", include_in_schema=False)
def email_notifications_frontend():
    return FileResponse(
        FRONTEND_FILE,
        media_type="application/javascript",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/api/email-notifications/settings")
def get_email_settings(request: Request):
    MAIN.require_auth(request)
    return _public_config()


@router.post("/api/email-notifications/settings")
def save_email_settings(payload: EmailSettingsPayload, request: Request):
    MAIN.require_auth(request)
    incoming = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    with CONFIG_LOCK:
        preserve_password = str(CONFIG.get("password") or "")
        incoming["last_ui_language"] = CONFIG.get("last_ui_language", "en")
        cleaned = _clean_config(incoming, preserve_password=preserve_password)
        CONFIG.clear()
        CONFIG.update(cleaned)
        _write_json(CONFIG_FILE, dict(CONFIG))
    return _public_config()


@router.post("/api/email-notifications/ui-language")
def save_ui_language(payload: UiLanguagePayload, request: Request):
    MAIN.require_auth(request)
    language = str(payload.language or "").lower()
    if language not in SUPPORTED_LANGUAGES - {"auto"}:
        raise HTTPException(status_code=400, detail="invalid_language")
    with CONFIG_LOCK:
        CONFIG["last_ui_language"] = language
        _write_json(CONFIG_FILE, dict(CONFIG))
    return {"success": True, "language": language}


@router.post("/api/email-notifications/test")
def send_test_email(request: Request):
    MAIN.require_auth(request)
    with CONFIG_LOCK:
        cfg = dict(CONFIG)
    _validate_sendable(cfg)
    lang = _resolve_language(cfg)
    try:
        _smtp_send(cfg, _tr(lang, "test_subject"), _tr(lang, "test_body"))
        _record_send_success()
    except Exception as exc:
        _record_send_error(exc)
        raise HTTPException(
            status_code=502,
            detail={"reason": "email_send_failed", "message": str(exc)[:300]},
        )
    return {"success": True}


async def _startup_email_monitor():
    asyncio.create_task(_monitor_loop())


def install(app, main_module):
    global MAIN, INSTALLED
    MAIN = main_module
    if INSTALLED:
        return
    INSTALLED = True
    app.include_router(router)
    app.add_event_handler("startup", _startup_email_monitor)
