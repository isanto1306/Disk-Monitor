# Disk Monitor for ZimaOS

Disk Monitor is a self-hosted storage and SMART monitoring dashboard for ZimaOS/Linux.

> **Repository initialization in progress:** the public repository structure is being prepared. `app/main.py` and the current `static/index.html` have not been committed yet, so **do not clone or build this repository yet**.

> **Development status:** community project / pre-release. The project is still under active development and hardware behavior can differ between SATA/SAS, NVMe and USB bridge controllers.

## Current development versions

- Backend: `0.22.14`
- Frontend: `0.32.76`

## Features

- Physical disk discovery for HDD, SSD, NVMe and supported USB storage
- Capacity, mount points and current disk activity
- Power-state / standby monitoring
- SMART health, temperature and detailed SMART attributes
- SMART history
- Manual SMART refresh and full SMART check
- Automatic SMART refresh: Off, 1×, 2× or 3× daily
- Automatic SMART checks avoid waking sleeping HDDs
- RAID detection, RAID member overview and SMART integration
- RAID standby controls with safety checks
- ZimaOS standby-timer integration where available
- Current process/path attribution where the host exposes enough information
- German and English UI
- Desktop, tablet and mobile responsive work in progress

## SMART automation

For `3× daily`, the day is split into these windows:

- `00:00–08:00`
- `08:00–16:00`
- `16:00–24:00`

A mechanical HDD is not woken just to run the automatic SMART refresh. When a drive is confirmed awake in an open time window, Disk Monitor waits about 45 seconds and refreshes SMART if the drive is still awake.

Manual SMART actions are separate and may intentionally wake a sleeping disk.

## Security

Disk Monitor needs deep hardware access. The current Docker design uses:

- `network_mode: host`
- `privileged: true`
- read-only host `/sys` and `/proc` mounts
- writable `/dev` access for SMART and explicit standby commands

Treat a compromise of this container as a potential host compromise.

**Do not expose port `8999` directly to the public Internet.** Use Disk Monitor on a trusted LAN or behind a properly configured HTTPS reverse proxy and firewall.

The application has no default public login. It requires private credentials and a session secret through `.env`.

Never commit or share:

- `.env`
- runtime cache files
- SMART history/cache containing drive identities or serial numbers
- host logs containing private paths or machine-specific information

## Installation

The commands below will apply **after the current source files have been added to the repository**.

```bash
git clone https://github.com/isanto1306/Disk-Monitor.git disk-monitor
cd disk-monitor
cp .env.example .env
```

Edit `.env` and set your own values. Generate a session secret, for example:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then:

```bash
docker compose build --no-cache
docker compose up -d
```

Open:

```text
http://<ZIMAOS-HOST>:8999
```

## Update during development

```bash
git pull
docker compose down
docker compose build --no-cache
docker compose up -d
```

The local `./cache` directory remains persistent and is excluded from Git.

## Important standby rule

Normal monitoring must not wake a sleeping mechanical HDD merely to collect monitoring or SMART data. Explicit manual actions are the exception.

USB bridge behavior varies significantly by enclosure/controller. A state reported as estimated standby is not always equivalent to a directly queryable SATA/SAS standby state.

## License

No license is included yet. Until a license is added, normal copyright rules apply; the repository being public does not automatically grant reuse, modification or redistribution rights.
