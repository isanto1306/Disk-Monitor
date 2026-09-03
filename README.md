# Disk Monitor for ZimaOS

Disk Monitor is a self-hosted storage and SMART monitoring dashboard for ZimaOS/Linux.

> **Development status:** community project / pre-release. The project is still under active development and hardware behavior can differ between SATA/SAS, NVMe and USB bridge controllers.

## Current development versions

- Backend: `0.22.33`
- Frontend: `0.32.77`

## Docker image

The current image is published automatically to GitHub Container Registry:

```text
ghcr.io/isanto1306/disk-monitor:latest
```

## Features

- Physical disk discovery for HDD, SSD, NVMe and supported USB storage
- Capacity, mount points and current disk activity
- Power-state / standby monitoring
- SMART health, temperature and detailed SMART attributes
- SMART history
- Manual SMART refresh and full SMART check
- One-time first-install full SMART check across all detected drives
- Automatic SMART refresh: Off, 1×, 2× or 3× daily
- Normal automatic SMART checks avoid waking sleeping HDDs
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

After the initial installation check has been completed, the normal automatic SMART refresh follows the no-wake rule: a mechanical HDD is not woken just to run a scheduled SMART refresh. When a drive is confirmed awake in an open time window, Disk Monitor waits about 45 seconds and refreshes SMART if the drive is still awake.

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

```bash
git clone https://github.com/isanto1306/Disk-Monitor.git disk-monitor
cd disk-monitor
cp .env.example .env
```

Edit `.env` and set your own values. Generate a session secret, for example:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Then pull and start the published image:

```bash
docker compose pull
docker compose up -d
```

Open:

```text
http://<ZIMAOS-HOST>:8999
```

## First start / important setup

### Initial SMART check on a fresh installation

On the first start of a **genuinely fresh installation with an empty persistent Disk Monitor cache**, Disk Monitor performs one full SMART check across all detected physical drives.

This first check is intentionally different from normal monitoring:

- Sleeping mechanical HDDs may be woken so the initial SMART data can be collected.
- SATA/SAS HDDs, supported USB HDDs, SSDs and NVMe drives are included when detected and supported by the controller/bridge.
- The check is attempted once for every detected physical drive.
- The same persistent result state used by the manual **SMART CHECK** is written automatically, so the header status and per-drive results reflect the first-run check.
- While the drives are already deliberately awake for this initialization, Disk Monitor performs a first-run-only filesystem-usage read so the **used capacity** is available in the summary and individual drive cards.
- The open dashboard periodically synchronizes the SMART full-check state, so the header/result status updates after the first-run check without requiring a manual page refresh.
- A persistent marker is stored in the Disk Monitor cache after the initial pass. Any later container restart or normal application update with an existing cache uses the regular no-wake startup behavior and does **not** run another wake-all initialization check.
- The first-run capacity seeding is local to this initialization path; it does not replace the normal no-wake capacity policy.
- If a controller or USB bridge does not support SMART correctly, the check for that device can fail even though the drive itself is otherwise usable.

After this one-time installation check, Disk Monitor returns to its normal no-wake behavior for automatic monitoring and scheduled SMART refreshes.

### USB HDD standby time

USB enclosures and USB-to-SATA bridges often do not expose their real standby timer or power state reliably. If you use a mechanical USB HDD, first determine approximately how long that drive/enclosure takes to enter standby after the last disk activity.

Then enter the same value in Disk Monitor under the USB auto-standby setting for that drive.

Important:

- This value is used only for passive standby estimation inside Disk Monitor.
- Disk Monitor does **not** change the USB enclosure's real standby timer with this setting.
- Disk Monitor does not intentionally wake a sleeping USB HDD just to verify the estimate during normal monitoring.
- If the configured time does not match the enclosure's actual behavior, the displayed estimated standby state may be inaccurate.

## Update during development

```bash
git pull
docker compose pull
docker compose up -d
```

The local `./cache` directory remains persistent and is excluded from Git.

## Build from source

The repository still contains the `Dockerfile` and source files used by GitHub Actions. To build locally instead of using GHCR:

```bash
docker build -t disk-monitor-local .
```

## Important standby rule

Normal monitoring must not wake a sleeping mechanical HDD merely to collect monitoring or SMART data. The deliberate exceptions are explicit manual actions and the one-time initial SMART refresh on a genuinely fresh installation.

USB bridge behavior varies significantly by enclosure/controller. A state reported as estimated standby is not always equivalent to a directly queryable SATA/SAS standby state.

For mechanical USB HDDs, configure Disk Monitor's expected USB auto-standby time to match the enclosure's observed idle-to-standby delay. This setting is only used for passive estimation and does not program the enclosure itself.

## License

No license is included yet. Until a license is added, normal copyright rules apply; the repository being public does not automatically grant reuse, modification or redistribution rights.
