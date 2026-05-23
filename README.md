# Family Planner Calendar

Un visualizzatore di calendario minimalista, ispirato alla tipografia del *Wall Street Journal*, progettato per girare su **Raspberry Pi** con display HDMI o e-ink. Include un server web per la visualizzazione in browser e la configurazione remota.

---

## Caratteristiche

- **Viste calendario**: annuale, mensile, settimanale, giornaliera e dettaglio appuntamento
- **Sorgenti CalDAV**: Apple Calendar / iCloud e file `.ics` locali
- **Display HDMI**: finestra pygame (SDL2) con ciclo di refresh configurabile — nessun browser richiesto
- **Display e-ink Waveshare**: quantizzazione palette (BW / BWR / 4 grigi) e dithering Floyd-Steinberg opzionale
- **Server web FastAPI**: anteprima browser e configurazione remota via interfaccia web
- **Modalità notte**: supportata su display HDMI/browser; e-ink usa sempre la modalità giorno
- **4 pulsanti fisici**: mappatura Su / Giù / Invio / Esci tramite GPIO o tastiera

---

## Requisiti Hardware

| Componente | Minimo | Consigliato |
|---|---|---|
| SBC | Raspberry Pi 3B | Raspberry Pi 4 / 5 |
| Memoria | 1 GB RAM | 2 GB RAM |
| Storage | 8 GB SD Class 10 | 16 GB SD A1 |
| Display | HDMI 1080p **oppure** Waveshare e-ink 7.5" V2 | — |
| OS | Raspberry Pi OS Lite (Bookworm 64-bit) | — |

---

## Requisiti Software

- Python 3.11+
- Dipendenze elencate in `requirements.txt`

**Su Raspberry Pi**: SDL2 è richiesto per la modalità HDMI (`libsdl2-dev`). Le librerie Waveshare sono necessarie solo per la modalità e-ink.

---

## Installazione

### 1. Clona il repository

```bash
git clone https://github.com/<org>/family-planner.git
cd family-planner
```

### 2. Crea un virtualenv e installa le dipendenze

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Copia e personalizza la configurazione

```bash
cp config/default.yaml config/config.yaml
```

Modifica `config/config.yaml` con i tuoi dati (URL CalDAV, credenziali, tipo di display). Imposta i permessi corretti per proteggere le credenziali:

```bash
chmod 600 config/config.yaml
```

> **Sicurezza**: per Apple Calendar usa una **App-Specific Password** generata su [appleid.apple.com](https://appleid.apple.com). Non usare mai la password dell'Apple ID direttamente.

---

## Avvio Locale (sviluppo e test)

```bash
source .venv/bin/activate
python app/main.py --config config/config.yaml
```

Apri il browser su `http://localhost:8080` per visualizzare il calendario o accedere all'interfaccia di configurazione (`/config`).

Per un avvio rapido usa lo script:

```bash
./scripts/start.sh
```

---

## Deploy su Raspberry Pi

Assicurati che la chiave SSH sia configurata per l'accesso al dispositivo, quindi:

```bash
./scripts/deploy.sh pi@<ip-raspberry>
```

Per configurare l'avvio automatico come servizio systemd:

```bash
./scripts/setup-autostart.sh pi@<ip-raspberry>
```

Il servizio viene registrato come `family-planner.service` e si avvia automaticamente al boot.

---

## Configurazione

Il file YAML è validato tramite **Pydantic v2** all'avvio. Un errore di schema blocca il processo con un messaggio diagnostico chiaro.

```yaml
server:
  host: "0.0.0.0"
  port: 8080

display:
  type: "hdmi"               # "hdmi" | "eink"
  fullscreen: false
  width: 1920
  height: 1080
  refresh_interval: 300      # secondi tra un aggiornamento e l'altro
  # Solo per e-ink:
  eink_model: "7in5_V2"
  eink_palette: "bwr"        # "bw" | "bwr" | "4gray"
  eink_dither: true

calendars:
  - name: "Famiglia"
    type: "caldav"
    url: "https://caldav.icloud.com"
    username: "utente@icloud.com"
    password: "xxxx-xxxx-xxxx-xxxx"   # App-Specific Password
    color: "#4A90D9"

  - name: "Locale"
    type: "ics"
    path: "/home/pi/calendars/locale.ics"
    color: "#E74C3C"
```

La configurazione può essere modificata anche via interfaccia web su `http://<host>:8080/config`.

---

## Struttura del Progetto

```
family-planner/
├── app/
│   ├── main.py              # Entry point
│   ├── config.py            # Caricamento e validazione config (Pydantic v2)
│   ├── server/              # FastAPI app, rotte, template Jinja2
│   ├── calendar/            # Provider CalDAV / ICS e aggregatore
│   ├── renderer/            # Pipeline rendering Pillow (HDMI + e-ink)
│   └── display/             # Gestori display pygame (HDMI) e Waveshare (e-ink)
├── config/
│   └── default.yaml         # Configurazione di default
├── scripts/                 # Script deploy, install, autostart
├── systemd/                 # Unit file systemd
├── docs/
│   ├── architecture.md      # Architettura e stack tecnico
│   └── design.md            # Design system (tipografia, palette, layout)
└── requirements.txt
```

---

## Architettura — Pipeline di Rendering

```
CalendarAggregator (CalDAV / ICS)
        │
        ▼
  ImageRenderer (Pillow)
        │
        ├── HDMI ──▶ HdmiDisplay (pygame / SDL2)
        │
        └── E-ink ──▶ EinkRenderer (quantizzazione + dithering)
                            │
                            └── EinkDisplay (SPI Waveshare)
```

La pipeline è condivisa: il rendering Pillow è identico per entrambi i display. Solo il post-processing finale differisce.

---

## Licenza

MIT — vedi [LICENSE](LICENSE).
