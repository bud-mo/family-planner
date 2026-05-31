# Family Planner Calendar

Un visualizzatore di calendario minimalista, ispirato alla tipografia del *Wall Street Journal*, progettato per girare su **Raspberry Pi** con display HDMI o e-ink. Include un server web per la visualizzazione in browser e la configurazione remota.

---

## Caratteristiche

- **Calendario + Meteo**: banner con data, icona meteo e temperature da **Open-Meteo** (nessuna API key richiesta)
- **Sorgenti calendario**: Apple Calendar / iCloud (CalDAV), Google Calendar e feed iCal generici, file `.ics` locali
- **Layout portrait e landscape**: selezionabile da configurazione, adattabile a qualsiasi risoluzione
- **Rotazione schermo**: supporto a 0°/90°/180°/270° via `display.rotation` — il post-processor EinkRenderer ruota l'immagine finale prima dell'invio al pannello
- **Modalità artwork (privacy)**: pressione del pulsante B (o tasto `B` su HDMI) mostra un dipinto casuale di dominio pubblico dall'**Art Institute of Chicago** al posto del calendario; pressione A ripristina il planner
- **Schermata di spegnimento**: pressione del pulsante D (o tasto `D` su HDMI) mostra un'ultima artwork sul pannello prima dello spegnimento del dispositivo
- **Display HDMI**: finestra pygame (SDL2) con ciclo di refresh configurabile — nessun browser richiesto
- **Display e-ink Waveshare**: quantizzazione palette (BW / BWR / 4 grigi / Spectra 6) e dithering Floyd-Steinberg opzionale
- **Server web FastAPI**: anteprima browser (`GET /`) e configurazione remota (`GET/POST /config`)
- **Navigazione**: Su / Giù / Oggi tramite GPIO, tastiera pygame o richieste `POST /state`

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

weather:
  enabled: true              # false → nasconde la sezione meteo
  latitude: 45.4654          # coordinate GPS della posizione
  longitude: 9.1866
  units: "celsius"           # "celsius" | "fahrenheit"

display:
  type: "hdmi"               # "hdmi" | "eink"
  layout: "landscape"        # "landscape" | "portrait"
  width: 1024
  height: 600
  fullscreen: false          # true → fullscreen; false → finestra dimensionata (sviluppo)
  refresh_interval: 300      # secondi tra un aggiornamento e l'altro
  show_buttons: false        # mostra pulsanti di navigazione (solo HDMI touchscreen)
  rotation: 0                # rotazione schermo: 0 | 90 | 180 | 270
  # Solo per e-ink:
  eink_model: 7in5_V2
  eink_palette: bw           # bw | bwr | 4gray | spectra6
  eink_dither: true

artwork:
  query: "landscape painting"  # query per ricerca artwork (Art Institute of Chicago)

calendars:
  - name: "Famiglia"
    type: "caldav"
    url: "https://caldav.icloud.com"
    username: "utente@icloud.com"
    password: "xxxx-xxxx-xxxx-xxxx"   # App-Specific Password Apple ID
    color: "#4A90D9"

  - name: "Google Calendar"
    type: "ical"
    url: "https://calendar.google.com/calendar/ical/<id>/basic.ics"
    color: "#27AE60"

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
│   ├── calendar/            # Provider CalDAV / iCal / ICS e aggregatore
│   ├── renderer/            # Pipeline rendering Pillow (HDMI + e-ink)
│   ├── weather/             # OpenMeteoProvider con cache in-memory TTL 1h
│   └── display/             # Gestori display pygame (HDMI) e Waveshare (e-ink)
├── config/
│   └── default.yaml         # Configurazione di default
├── scripts/                 # Script deploy, install, autostart
├── systemd/                 # Unit file systemd
├── docs/
│   ├── architecture.md      # Architettura e stack tecnico
│   ├── design.md            # Design system (tipografia, palette, layout)
│   └── artworks.md          # Gestione artwork (Art Institute of Chicago API)
└── requirements.txt
```

---

## Architettura — Pipeline di Rendering

```
CalendarAggregator (CalDAV / iCal / ICS)
        │
        ▼
PillowEinkRenderer (Pillow nativo)
        │
        ├── HDMI ──▶ HdmiDisplay (pygame / SDL2)
        │
        └── E-ink ──▶ EinkRenderer (quantizzazione palette + dithering Floyd-Steinberg)
                            │
                            └── EinkDisplay (SPI Waveshare)
```

La pipeline è condivisa: `PillowEinkRenderer` genera la stessa `PIL.Image` per entrambi i display. Solo il post-processing finale differisce. Il meteo è iniettato da `OpenMeteoProvider` (cache in-memory TTL 1h, API Open-Meteo senza chiave).

`PillowEinkRenderer.render_artwork()` è un secondo entry point dello stesso renderer: recupera un dipinto casuale di dominio pubblico dall'**Art Institute of Chicago** via IIIF e lo restituisce come `PIL.Image` dello stesso formato — la modalità privacy e la schermata di spegnimento usano questa stessa pipeline.

---

## Licenza

MIT — vedi [LICENSE](LICENSE).
