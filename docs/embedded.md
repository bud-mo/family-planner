# Best Practices - Embedded Device Configuration (Raspberry Pi)

This document gathers recommended practices for configuring a Raspberry Pi as an always-on embedded device, with special attention to **SD card longevity** and system stability.

> **Reference target**: Raspberry Pi OS Lite **Bookworm 64-bit** on **Raspberry Pi 5** (4/8/16 GB) and **Raspberry Pi Zero 2 W** (512 MB). Two cross-cutting notes for the entire document:
> - **Boot path**: on Bookworm the FAT partition is mounted at **`/boot/firmware`**, *not* `/boot`. All references to `config.txt` and configuration files editable from another PC therefore use `/boot/firmware/...`. A file written to `/boot/` ends up on the root ext4 partition and is **not** readable when mounting the SD card on Windows/macOS.
> - **Limited RAM on Zero 2 W**: with only 512 MB, `tmpfs` sizing and `zram` usage (sections 1 and 5) must be tuned carefully to avoid memory saturation.

---

## 1. Move Logs from SD to RAM (`tmpfs`)

The main cause of early SD card wear is continuous writes of logs and temporary files. The solution is to mount these directories on `tmpfs` (RAM), so writes are absorbed by volatile memory instead of flash.

### 1.1 `/etc/fstab` configuration

Add the following lines to `/etc/fstab`:

```
tmpfs   /tmp            tmpfs   defaults,noatime,nosuid,size=64m    0 0
tmpfs   /var/log        tmpfs   defaults,noatime,nosuid,mode=0755,size=64m  0 0
tmpfs   /var/tmp        tmpfs   defaults,noatime,nosuid,size=32m    0 0
```

> **Warning**: logs in `/var/log` are lost at every reboot. For persistent debugging, use `journald` with `volatile` storage (see below) or mount an external disk for logs.

> **Do not mount `/var/cache/apt` on a small tmpfs**: during `apt update`/`apt upgrade`, downloaded packages can easily exceed 32-64 MB, and an undersized tmpfs can make updates fail with *"No space left on device"*. If SD wear happens only during updates (a rare event on an embedded device), it is better to keep `/var/cache/apt` on SD and run `sudo apt clean` after each update (section 6.2).

> **Zero 2 W (512 MB)**: `size=` values above are **maximum caps**, not fixed allocations. tmpfs only uses RAM for data actually written. However, combined with potential `zram` pages (section 5), on 512 MB it is often better to reduce them: for example, `/var/log` to `size=32m` and `/tmp` to `size=32m`. Verify with `df -h /var/log /tmp` and `free -h` under real load.

### 1.2 `systemd-journald` in volatile mode

Edit `/etc/systemd/journald.conf`:

```ini
[Journal]
Storage=volatile
RuntimeMaxUse=32M
Compress=yes
```

This forces `journald` to write only to `/run/log/journal` (already in RAM), not to disk.

Apply immediately without rebooting:

```bash
sudo systemctl restart systemd-journald
```

### 1.3 Disable rsyslog (optional)

If `rsyslog` is active and writes to `/var/log/syslog`, disable it if you do not need persistent logs:

```bash
sudo systemctl disable rsyslog
sudo systemctl stop rsyslog
```

---

## 2. Mount Options to Reduce Writes

### 2.1 `noatime` and `nodiratime`

The SD card is written every time a file is **read** (access time update). Disable this behavior with `noatime` in `/etc/fstab` on the root partition:

```
PARTUUID=xxxxxxxx-02  /  ext4  defaults,noatime,nodiratime  0  1
```

> On recent Raspberry Pi OS versions, `noatime` may already be enabled by default. Verify with `mount | grep " / "`.

### 2.2 ext4 `commit` interval

Increasing the ext4 journal commit interval reduces disk sync frequency:

```
PARTUUID=xxxxxxxx-02  /  ext4  defaults,noatime,commit=600  0  1
```

The value `600` means the filesystem flushes data every 600 seconds instead of the default 5 seconds.

---

## 3. Read-Only Filesystem (Read-Only Root)

For stable embedded devices, the root filesystem can be mounted read-only. This completely removes SD writes during normal operation.

### 3.1 Enable overlay filesystem (Raspberry Pi OS)

Raspberry Pi OS includes a dedicated tool:

```bash
sudo raspi-config
# -> Performance Options -> Overlay File System -> Enable
```

This mounts root as read-only and uses a tmpfs overlay for temporary writes. All changes are lost at reboot, which is ideal for kiosk-like devices.

### 3.2 Selective persistence with bind mount

To keep only specific paths persistent (for example Family Planner configuration):

```
# /etc/fstab
/boot/firmware/family-planner.config.yaml  /home/pi/family-planner/config/config.yaml  none  bind  0  0
```

This way, the configuration file lives on `/boot/firmware` (FAT32 partition, easily editable from any computer) and is mounted into the location expected by the application.

> **Bookworm note**: on Raspberry Pi OS Bookworm the FAT partition is `/boot/firmware`, not `/boot`. Accordingly, `family-planner.service` should also point to `--config /boot/firmware/family-planner.config.yaml`. A bind mount on a single file requires the destination file to **already exist** (create an empty file with `touch` before the first mount).

---

## 4. systemd Configuration for Fast Startup

### 4.1 Optimized unit file

The file `systemd/family-planner.service` already uses `After=network-online.target`. For faster startup on slow or unavailable networks, consider:

```ini
[Unit]
Description=Family Planner Calendar Server
After=network.target
# Replace network-online.target with network.target
# so startup is not blocked if the router takes time
```

### 4.2 Restart timeout

Set a reasonable `RestartSec` to avoid rapid crash loops that stress the SD:

```ini
[Service]
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=120
StartLimitBurst=3
```

After 3 crashes in 120 seconds, the service stops restarting automatically.

### 4.3 `StandardOutput` and `StandardError` to volatile journal

In the service file, force output to journal (already volatile if configured in section 1.2):

```ini
[Service]
StandardOutput=journal
StandardError=journal
SyslogIdentifier=family-planner
```

---

## 5. Swap

Swap on SD card is extremely harmful for longevity. Disable it:

```bash
sudo dphys-swapfile swapoff
sudo dphys-swapfile uninstall
sudo systemctl disable dphys-swapfile
```

If RAM is insufficient - a typical case on **Raspberry Pi Zero 2 W (512 MB)**, where disabling swap entirely may risk OOM-killing the application - consider a swap file on USB disk or, better, compressed RAM swap (`zram`):

```bash
sudo apt install zram-tools
# /etc/default/zramswap
ALGO=lz4
PERCENT=25
```

`zram` creates a compressed swap device in RAM - much faster and with no SD stress.

> **Pi 5 vs Zero 2 W**: on Pi 5 (>= 4 GB), swap is rarely needed and can stay disabled. On Zero 2 W (512 MB), `zram` with `PERCENT=50` (about 256 MB compressed swap) is a good compromise to avoid OOM kills while keeping SD writes at zero.

---

## 6. Updates and Packages

### 6.1 Disable automatic updates

On an embedded device, automatic updates may rewrite system files unexpectedly:

```bash
sudo systemctl disable apt-daily.timer
sudo systemctl disable apt-daily-upgrade.timer
sudo systemctl disable man-db.timer
```

### 6.2 Clean APT cache

After each installation, clean cache to free space:

```bash
sudo apt clean
sudo apt autoremove --purge
```

---

## 7. Hardware Watchdog

Raspberry Pi includes a hardware watchdog. Enabling it guarantees automatic reboot in case of system lockups (kernel hang, deadlock).

### 7.1 Enable watchdog

In `/boot/firmware/config.txt` (on Raspberry Pi OS Bookworm - valid for both Pi 5 **and** Zero 2 W; the old `/boot/config.txt` path is only for pre-Bookworm OS):

```
dtparam=watchdog=on
```

> Reboot after the change and verify that the device exists: `ls /dev/watchdog*`. Logs will show `Broadcom BCM2835 Watchdog timer` (the same driver is used on Pi 5/Zero 2 W).

### 7.2 Configure `systemd` as watchdog supervisor

In `/etc/systemd/system.conf`:

```ini
RuntimeWatchdogSec=14
RebootWatchdogSec=2min
```

> **Hardware limit**: the BCM watchdog (including Pi 5 and Zero 2 W) supports a **maximum timeout of 15 seconds**; if you set a higher value, systemd silently clamps it. `14` is recommended to stay below the limit with margin.
>
> **Option name**: `ShutdownWatchdogSec` is **deprecated** - renamed to `RebootWatchdogSec` in systemd v243. Bookworm ships systemd 252, so use `RebootWatchdogSec` (the old name is still accepted as an alias but no longer documented).

---

## 8. Temperature and Throttling Monitoring

Thermal throttling causes extra log writes and instability. Check temperature with:

```bash
vcgencmd measure_temp
vcgencmd get_throttled
```

A `throttled` value different from `0x0` means the Pi has reduced clock speed because of overheating. Use a heatsink and/or fan.

> **Pi 5**: it runs significantly hotter than previous models and enters soft throttling at 80 C (hard at 85 C). For 24/7 use, the official **Active Cooler** (or equivalent with firmware-managed PWM fan) is recommended. **Zero 2 W**, with lower power draw, usually stays within limits with a small passive heatsink, but should still be verified under load in closed enclosures without ventilation.

---

## 9. SD Card Choice and Management

- Use **Application Class A1 or A2** cards (designed for intensive random I/O)
- Recommended brands: SanDisk Endurance, Samsung PRO Endurance (designed for CCTV/dashcam, with much higher write-cycle durability)
- Create a **backup image** of the SD card after the first working setup:
  ```bash
  sudo dd if=/dev/mmcblk0 bs=4M status=progress | gzip > backup-$(date +%Y%m%d).img.gz
  ```
- Consider a **USB drive** (external SSD or USB 3.0 stick) to mount `/var` or the whole home, leaving SD only for boot

---

## 10. Post-Installation Checklist

| # | Check | Command |
|---|---|---|
| 1 | `tmpfs` mounted on `/tmp`, `/var/log` | `mount \| grep tmpfs` |
| 2 | `noatime` enabled on root | `mount \| grep " / "` |
| 3 | `journald` volatile | `journalctl --disk-usage` (must remain in RAM) |
| 4 | Swap disabled or on zram | `free -h` |
| 5 | Watchdog enabled | `ls /dev/watchdog*` |
| 6 | Temperature below 70 C at steady state | `vcgencmd measure_temp` |
| 7 | Automatic updates disabled | `systemctl status apt-daily.timer` |
| 8 | `family-planner.service` active and stable | `systemctl status family-planner` |
