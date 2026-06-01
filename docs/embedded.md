# Best Practices — Configurazione Dispositivi Embedded (Raspberry Pi)

Questo documento raccoglie le pratiche consigliate per la configurazione di un Raspberry Pi come dispositivo embedded sempre attivo, con particolare attenzione alla **longevità della scheda SD** e alla stabilità del sistema.

---

## 1. Spostare i Log dalla SD alla RAM (`tmpfs`)

La principale causa di usura anticipata delle schede SD è la scrittura continua di log e file temporanei. La soluzione è montare queste directory su `tmpfs` (RAM), in modo che i write vengano assorbiti dalla memoria volatile invece che dalla flash.

### 1.1 Configurazione `/etc/fstab`

Aggiungere le seguenti righe a `/etc/fstab`:

```
tmpfs   /tmp            tmpfs   defaults,noatime,nosuid,size=64m    0 0
tmpfs   /var/log        tmpfs   defaults,noatime,nosuid,mode=0755,size=64m  0 0
tmpfs   /var/tmp        tmpfs   defaults,noatime,nosuid,size=32m    0 0
tmpfs   /var/cache/apt  tmpfs   defaults,noatime,nosuid,size=32m    0 0
```

> **Attenzione**: i log in `/var/log` vengono persi ad ogni riavvio. Per debug persistente usare `journald` con storage `volatile` (vedi sotto) o montare un disco esterno per i log.

### 1.2 `systemd-journald` in modalità volatile

Modificare `/etc/systemd/journald.conf`:

```ini
[Journal]
Storage=volatile
RuntimeMaxUse=32M
Compress=yes
```

Questo forza `journald` a scrivere solo in `/run/log/journal` (già in RAM), non su disco.

Applicare subito senza riavviare:

```bash
sudo systemctl restart systemd-journald
```

### 1.3 Disabilitare rsyslog (opzionale)

Se `rsyslog` è attivo e scrive su `/var/log/syslog`, disabilitarlo se non si ha bisogno di log persistenti:

```bash
sudo systemctl disable rsyslog
sudo systemctl stop rsyslog
```

---

## 2. Opzioni di Mount per Ridurre le Scritture

### 2.1 `noatime` e `nodiratime`

La SD card viene scritta ogni volta che un file viene **letto** (aggiornamento dell'access time). Disabilitare con `noatime` in `/etc/fstab` sulla partizione root:

```
PARTUUID=xxxxxxxx-02  /  ext4  defaults,noatime,nodiratime  0  1
```

> Su Raspberry Pi OS recente, `noatime` è già abilitato di default su alcune versioni. Verificare con `mount | grep " / "`.

### 2.2 `commit` interval per ext4

Aumentare l'intervallo di commit del journal ext4 riduce la frequenza di sync su disco:

```
PARTUUID=xxxxxxxx-02  /  ext4  defaults,noatime,commit=600  0  1
```

Il valore `600` significa che il filesystem sincronizza i dati ogni 600 secondi invece dei 5 secondi di default.

---

## 3. Filesystem in Sola Lettura (Read-Only Root)

Per dispositivi embedded stabili, il root filesystem può essere montato in sola lettura. Questo elimina completamente le scritture sulla SD durante il normale funzionamento.

### 3.1 Abilitare overlay filesystem (Raspberry Pi OS)

Raspberry Pi OS include un tool dedicato:

```bash
sudo raspi-config
# → Performance Options → Overlay File System → Enable
```

Questo monta il root in read-only e usa un overlay tmpfs per le scritture temporanee. Tutte le modifiche vengono perse al riavvio — ideale per dispositivi kiosk.

### 3.2 Persistenza selettiva con bind mount

Per rendere persistenti solo alcune directory (es. la configurazione di Family Planner):

```
# /etc/fstab
/boot/family-planner.config.yaml  /home/pi/family-planner/config/config.yaml  none  bind  0  0
```

In questo modo il file di configurazione risiede su `/boot` (partizione FAT32, facilmente modificabile da qualsiasi computer) e viene montato nella posizione attesa dall'applicazione.

---

## 4. Configurazione systemd per Avvio Rapido

### 4.1 Unit file ottimizzato

Il file `systemd/family-planner.service` usa già `After=network-online.target`. Per un avvio più rapido su rete lenta o assente, valutare:

```ini
[Unit]
Description=Family Planner Calendar Server
After=network.target
# Sostituire network-online.target con network.target
# per non bloccare l'avvio se il router impiega tempo
```

### 4.2 Timeout di restart

Impostare un `RestartSec` ragionevole per evitare cicli di crash rapidi che stressano la SD:

```ini
[Service]
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=120
StartLimitBurst=3
```

Dopo 3 crash in 120 secondi, il servizio smette di riavviarsi automaticamente.

### 4.3 `StandardOutput` e `StandardError` su journal volatile

Nel service file, forzare l'output su journal (già volatile se configurato al punto 1.2):

```ini
[Service]
StandardOutput=journal
StandardError=journal
SyslogIdentifier=family-planner
```

---

## 5. Swap

La swap su scheda SD è estremamente dannosa per la longevità. Disabilitarla:

```bash
sudo dphys-swapfile swapoff
sudo dphys-swapfile uninstall
sudo systemctl disable dphys-swapfile
```

Se la RAM è insufficiente (es. RPi 3B+ con 1 GB), valutare uno swap file su disco USB o RAM (zram):

```bash
sudo apt install zram-tools
# /etc/default/zramswap
ALGO=lz4
PERCENT=25
```

`zram` crea un dispositivo di swap compresso in RAM — molto più veloce e senza stress sulla SD.

---

## 6. Aggiornamenti e Pacchetti

### 6.1 Disabilitare gli aggiornamenti automatici

Su un dispositivo embedded, gli aggiornamenti automatici possono riscrivere file di sistema in modo inatteso:

```bash
sudo systemctl disable apt-daily.timer
sudo systemctl disable apt-daily-upgrade.timer
sudo systemctl disable man-db.timer
```

### 6.2 Pulizia cache APT

Dopo ogni installazione, pulire la cache per liberare spazio:

```bash
sudo apt clean
sudo apt autoremove --purge
```

---

## 7. Watchdog Hardware

Il Raspberry Pi ha un watchdog hardware integrato. Abilitarlo garantisce il riavvio automatico in caso di blocco del sistema (kernel hang, deadlock).

### 7.1 Abilitare il watchdog

In `/boot/config.txt` (o `/boot/firmware/config.txt` su RPi 5):

```
dtparam=watchdog=on
```

### 7.2 Configurare `systemd` come watchdog supervisor

In `/etc/systemd/system.conf`:

```ini
RuntimeWatchdogSec=15
ShutdownWatchdogSec=2min
```

---

## 8. Monitoraggio Temperatura e Throttling

Il throttling termico causa scritture aggiuntive sui log e instabilità. Verificare la temperatura con:

```bash
vcgencmd measure_temp
vcgencmd get_throttled
```

Un valore di `throttled` diverso da `0x0` indica che il Pi ha ridotto la frequenza per surriscaldamento. Usare un dissipatore e/o ventola.

---

## 9. Scelta e Gestione della Scheda SD

- Usare schede **Application Class A1 o A2** (progettate per I/O random intensivo)
- Brand consigliati: SanDisk Endurance, Samsung PRO Endurance (progettate per CCTV/dashcam, cicli di scrittura molto superiori)
- Creare un'**immagine di backup** dell'SD dopo il primo setup funzionante:
  ```bash
  sudo dd if=/dev/mmcblk0 bs=4M status=progress | gzip > backup-$(date +%Y%m%d).img.gz
  ```
- Considerare un **disco USB** (SSD esterno o chiavetta USB 3.0) per montare `/var` o l'intera home, lasciando la SD solo per il boot

---

## 10. Checklist Post-Installazione

| # | Verifica | Comando |
|---|---|---|
| 1 | `tmpfs` montato su `/tmp`, `/var/log` | `mount \| grep tmpfs` |
| 2 | `noatime` attivo sulla root | `mount \| grep " / "` |
| 3 | `journald` volatile | `journalctl --disk-usage` (deve restare in RAM) |
| 4 | Swap disabilitata o su zram | `free -h` |
| 5 | Watchdog abilitato | `ls /dev/watchdog*` |
| 6 | Temperatura sotto 70°C a regime | `vcgencmd measure_temp` |
| 7 | Aggiornamenti automatici disabilitati | `systemctl status apt-daily.timer` |
| 8 | `family-planner.service` attivo e stabile | `systemctl status family-planner` |
