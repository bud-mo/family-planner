# Architettura — Family Planner Calendar

## Panoramica

**Family Planner** è un visualizzatore di calendario ottimizzato per dispositivi Raspberry Pi (3+) con display HDMI o e-ink, eseguibile anche in locale (Mac/Linux) per sviluppo e test. Espone un servizio web sia per la visualizzazione del calendario sia per la sua configurazione.

---

## Stack Tecnologico

| Layer | Tecnologia |
|---|---|
| Linguaggio | Python 3.11+ |
| Web server | FastAPI + Uvicorn |
| Template HTML | Jinja2 |
| Rendering immagini | Pillow (PIL) |
| Calendario CalDAV | `caldav` + `icalendar` |
| Configurazione | YAML (`pyyaml`) + Pydantic v2 |
| Display HDMI (finestra) | pygame (SDL2) — finestra gestita interamente da Python |
| Display e-ink | Librerie Waveshare (opzionale, caricamento dinamico) |

---

## Struttura del Progetto

```
family-planner/
├── app/
│   ├── main.py                  # Entry point — parsing args, avvio server
│   ├── config.py                # Caricamento e validazione configurazione
│   ├── server/
│   │   ├── __init__.py
│   │   ├── app.py               # Definizione app FastAPI e rotte
│   │   ├── routes/
│   │   │   ├── index.py         # GET / — vista calendario
│   │   │   └── config.py        # GET/POST /config — configurazione UI
│   │   └── templates/           # Template Jinja2
│   │       ├── base.html
│   │       ├── calendar.html
│   │       └── config.html
│   ├── calendar/
│   │   ├── __init__.py
│   │   ├── base.py              # Classe astratta CalendarProvider
│   │   ├── caldav_provider.py   # Provider CalDAV (Apple Calendar / iCloud)
│   │   ├── ics_provider.py      # Provider file .ics locali
│   │   ├── ical_provider.py     # Provider iCal URL (Google Calendar, feed pubblici)
│   │   └── aggregator.py        # Aggrega eventi da più provider
│   ├── renderer/
│   │   ├── __init__.py
│   │   ├── base.py              # Classe astratta Renderer
│   │   ├── image_renderer.py    # Render calendario → PIL Image (pipeline comune)
│   │   └── eink_renderer.py     # Post-processing e-ink: quantizzazione palette, dithering
│   └── display/
│       ├── __init__.py
│       ├── hdmi.py              # Finestra pygame: PIL Image → SDL Surface → schermo
│       └── eink.py              # Gestore display e-ink (push immagine via SPI)
├── config/
│   └── default.yaml             # Configurazione di default (inclusa nel repo)
├── scripts/
│   ├── deploy.sh                # Deploy via SSH su Raspberry Pi
│   ├── install.sh               # Installazione dipendenze sul dispositivo
│   ├── setup-autostart.sh       # Setup servizi systemd sul dispositivo
│   └── start.sh                 # Avvio locale semplificato
├── systemd/
│   └── family-planner.service   # Servizio systemd per l'app Python
├── docs/
│   ├── design.md                # UX/UI design (riferimento per il rendering)
│   └── architecture.md          # Questo file
├── requirements.txt
└── README.md
```

---

## Configurazione

Il file di configurazione è in formato **YAML**. La sua posizione è passata come argomento CLI all'avvio:

```bash
python app/main.py --config /path/to/config.yaml
```

Se non specificato, il fallback è `./config/default.yaml`.

### Schema del file di configurazione

```yaml
server:
  host: "0.0.0.0"
  port: 8080

display:
  fullscreen: false          # true → pygame fullscreen; false → finestra normale
  type: "hdmi"               # "hdmi" | "eink"
  width: 1920
  height: 1080
  refresh_interval: 300      # secondi tra un aggiornamento e l'altro
  eink_model: "7in5_V2"     # modello Waveshare (solo se type: "eink")
  eink_palette: "bwr"        # palette e-ink: "bw" | "bwr" | "4gray" (solo se type: "eink")
  eink_dither: true          # abilita dithering Floyd-Steinberg (solo se type: "eink")

calendars:
  - name: "Famiglia"
    type: "caldav"
    url: "https://caldav.icloud.com"
    username: "utente@icloud.com"
    password: "app-specific-password"   # App-Specific Password Apple ID
    color: "#4A90D9"

  - name: "Calendario locale"
    type: "ics"
    path: "/home/pi/calendars/locale.ics"
    color: "#E74C3C"

  - name: "Google Calendar"
    type: "ical"
    url: "https://calendar.google.com/calendar/ical/<id>/basic.ics"  # anche webcal:// accettato
    color: "#27AE60"
```

La configurazione è validata tramite **Pydantic v2** all'avvio; errori di schema bloccano il processo con un messaggio chiaro.

---

## Flusso Applicativo

```
Avvio (main.py --config ...)
        │
        ▼
  Carica config.yaml  ──(errore)──▶  Exit con messaggio
        │
        ▼
  Inizializza CalendarAggregator
  (istanzia i provider definiti in config)
        │
        ▼
  Inizializza Display Manager
  (HDMI → finestra pygame; e-ink → push periodico via SPI)
        │
        ▼
  Avvia FastAPI / Uvicorn (thread separato)
        │
        ├─── GET /          ──▶  Fetch eventi → Render HTML calendario (anteprima web)
        ├─── GET /config    ──▶  Mostra form di configurazione
        └─── POST /config   ──▶  Salva config.yaml → Riavvio graceful
```

---

## Rotte Web

### `GET /`
Anteprima web del calendario (HTML/Jinja2). Disponibile per debug e per la configurazione. **Non è più utilizzata per il display HDMI** — la finestra pygame legge direttamente dal renderer Pillow interno senza passare per HTTP.

Per display **e-ink**, la rotta è comunque disponibile per ispezione.

### `GET /config`
Interfaccia web per la configurazione: aggiunta/rimozione calendari, modifica parametri di visualizzazione, test della connessione ai provider.

### `POST /config`
Salva le modifiche nel file di configurazione e riavvia il server in modo graceful (SIGHUP o riavvio Uvicorn).

---

## Integrazione Apple Calendar

Apple Calendar è supportato via **CalDAV** attraverso iCloud:

- **URL endpoint**: `https://caldav.icloud.com`
- **Autenticazione**: App-Specific Password generata su [appleid.apple.com](https://appleid.apple.com) (richiesta per account con 2FA attivo)
- **Libreria**: `caldav` (Python)
- Il provider recupera tutti i calendari disponibili sull'account e filtra per nome se specificato

> **Nota sicurezza**: la password non è mai esposta via API web. Il file di configurazione deve avere permessi `600`.

---

## Integrazione Google Calendar (e feed iCal generici)

Google Calendar e qualsiasi servizio che espone un feed iCalendar via HTTP/HTTPS sono supportati dal tipo `ical`:

- **URL**: si ottiene da Google Calendar → *Impostazioni* → *Integra il calendario* → *Indirizzo segreto in formato iCal*
- **Autenticazione**: non richiesta — l'URL funge da token segreto; non è mai necessario username/password
- **Schema `webcal://`**: accettato e convertito automaticamente in `https://` da `IcalProvider`
- **Libreria**: `requests` (già inclusa) + `icalendar` (stessa pipeline di `IcsProvider`)

```yaml
calendars:
  - name: "Google Calendar"
    type: "ical"
    url: "https://calendar.google.com/calendar/ical/<id>/basic.ics"
    color: "#27AE60"
```

> **Nota sicurezza**: l'URL iCal di Google Calendar contiene un identificatore segreto. Trattarlo come una password: non condividerlo e non includerlo nei log. Il file di configurazione deve avere permessi `600`.

---

## Strategie di Display

### Architettura comune (pipeline unificata)

Entrambi i display (HDMI ed e-ink) condividono la stessa pipeline di rendering basata su Pillow:

```
CalendarAggregator
       │
       ▼
 ImageRenderer            ← disegna il calendario su un oggetto PIL.Image
 (image_renderer.py)        usando Pillow: testo, rettangoli, font TrueType
       │
       ├──── HDMI ─────▶  HdmiDisplay (hdmi.py)
       │                   PIL Image → pygame.Surface → schermo SDL
       │
       └──── E-ink ────▶  EinkRenderer (eink_renderer.py)
                           → quantizzazione palette (BW / BWR / 4 grigi)
                           → dithering Floyd-Steinberg (opzionale)
                           → EinkDisplay (eink.py) → push via SPI Waveshare
```

### HDMI — finestra pygame

`display/hdmi.py` gestisce una finestra **pygame** (SDL2). Python ha pieno controllo del ciclo di vita della finestra: creazione, aggiornamento periodico, chiusura.

**Vantaggi rispetto a Chromium kiosk:**
- Nessuna dipendenza da browser o da X11/Wayland
- Su Raspberry Pi funziona direttamente sul framebuffer KMS/DRM (`SDL_VIDEODRIVER=kmsdrm`) senza session grafica
- Stessa pipeline Pillow usata per l'e-ink → zero duplicazione
- Avvio più veloce; consumo di memoria inferiore

**Modalità operative:**

| Configurazione | Comportamento |
|---|---|
| `fullscreen: false` | Finestra normale (sviluppo su Mac / Linux desktop) |
| `fullscreen: true` | `pygame.FULLSCREEN` — copre l'intero display |
| RPi senza X11 | `SDL_VIDEODRIVER=kmsdrm SDL_AUDIODRIVER=dummy` nel service systemd |

**Loop di refresh (`hdmi.py`):**
```python
pygame.init()
screen = pygame.display.set_mode((width, height), flags)
while running:
    image = aggregator.render()           # PIL Image
    surface = pygame.image.frombuffer(    # conversione zero-copy
        image.tobytes(), image.size, image.mode)
    screen.blit(surface, (0, 0))
    pygame.display.flip()
    clock.tick(1 / refresh_interval)
```

### E-ink (Waveshare) — post-processing Pillow

`renderer/eink_renderer.py` riceve la PIL Image base dall'`ImageRenderer` e applica una catena di trasformazioni prima di passarla al display fisico:

1. **Ridimensionamento** alla risoluzione nativa del pannello (es. 800×480 per `7in5_V2`)
2. **Quantizzazione palette** (`image.quantize(palette=...)` o `Image.convert("P")`):
   - `bw` — bianco/nero puro (1-bit)
   - `bwr` — bianco/nero/rosso (palette a 3 colori, per pannelli a colori)
   - `4gray` — 4 livelli di grigio (per pannelli EPD grigi)
3. **Dithering Floyd-Steinberg** (`Image.Dither.FLOYDSTEINBERG`) — attivabile via `eink_dither: true` in config; migliora la resa di sfumature e testo piccolo
4. Push al pannello via `eink.py` (libreria Waveshare caricata dinamicamente)

Il tipo di display e-ink (es. `7in5_V2`) è specificato in `config.yaml` sotto `display.eink_model`.

---

## Multipiattaforma

| Comportamento | Mac (sviluppo) | Linux / Raspberry Pi (produzione) |
|---|---|---|
| `display.fullscreen: false` | Finestra pygame normale | Finestra pygame normale |
| `display.fullscreen: true` | `pygame.FULLSCREEN` | `pygame.FULLSCREEN` + `SDL_VIDEODRIVER=kmsdrm` |
| Calendario | CalDAV iCloud via rete | CalDAV iCloud via rete |
| Avvio automatico | Manuale / script locale | systemd (`family-planner.service`) |

---

## Script di Deploy e Autostart

### `scripts/deploy.sh`
Esegue il deploy sul Raspberry Pi via SSH + `rsync`:

```
1. rsync dell'intera cartella (esclusi .git, __pycache__, venv)
2. SSH: pip install -r requirements.txt
3. SSH: systemctl daemon-reload && systemctl restart family-planner
```

Variabili configurabili: `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_PATH`.

### `scripts/install.sh`
Eseguito una tantum sul dispositivo:
- Installa dipendenze di sistema (`python3-pip`, librerie SDL2 per pygame, librerie SPI per e-ink)
- Crea il virtualenv
- Installa i pacchetti Python da `requirements.txt`
- Copia il file systemd in `/etc/systemd/system/`

### `scripts/setup-autostart.sh`
- Abilita e avvia il servizio systemd:
  - `family-planner.service` — server Python + finestra pygame (tutto in un unico processo)
- Imposta `SDL_VIDEODRIVER=kmsdrm` nell'environment del service per accesso diretto al framebuffer KMS/DRM

### `systemd/family-planner.service`
```ini
[Unit]
Description=Family Planner Calendar Server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/family-planner
Environment=SDL_VIDEODRIVER=kmsdrm
Environment=SDL_AUDIODRIVER=dummy
ExecStart=/home/pi/family-planner/venv/bin/python app/main.py --config /home/pi/family-planner/config.yaml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> **Nota**: `SDL_VIDEODRIVER=kmsdrm` consente a pygame di accedere direttamente al framebuffer KMS/DRM senza X11 o Wayland. Per RPi 3/4 con kernel recente è la modalità raccomandata. In alternativa `SDL_VIDEODRIVER=fbcon` per kernel più vecchi.

---

## Sicurezza

- Il file di configurazione (con credenziali) deve avere permessi `600` (`chmod 600 config.yaml`)
- Il server web è in ascolto su `0.0.0.0` di default; in produzione si raccomanda di limitare a `127.0.0.1` se la rotta `/config` non deve essere accessibile da rete
- Nessuna credenziale è mai esposta via API

---

## Dipendenze Principali (`requirements.txt`)

```
fastapi
uvicorn[standard]
jinja2
pydantic>=2.0
pyyaml
caldav
icalendar
pillow
pygame>=2.5          # finestra HDMI e conversione PIL→Surface
python-multipart     # per form POST /config
```

---

## Diagramma Componenti

```
┌─────────────────────────────────────────────┐
│                  main.py                     │
│  args parsing → config load → app start      │
└───────────┬─────────────────────┬────────────┘
            │                     │
    ┌───────▼──────┐     ┌────────▼────────────────────┐
    │  FastAPI App  │     │      Display Manager        │
    │  / (preview)  │     │  (avvia loop in thread)     │
    │  /config      │     └────────┬────────────────────┘
    └───────┬───────┘              │
            │               ┌─────▼──────────┐
    ┌───────▼──────┐        │ ImageRenderer  │
    │  Aggregator  │◄───────│ (Pillow)       │
    │  (calendari) │        └──────┬─────────┘
    └───────┬───────┘              │
            │              ┌───────┴────────┐
   ┌────────┴────────┐     │                │
   │                 │  ┌──▼──────┐  ┌──────▼──────────┐
┌──▼──────┐   ┌──────▼───┐   ┌──────▼───┐│  HDMI  │  │  EinkRenderer  │
│ CalDAV  │   │  ICS     │   │  iCal    ││Display │  │  palette/dither │
│Provider │   │ Provider │   │ Provider ││(pygame)│  └──────┬──────────┘
│(iCloud) │   │(file)    │   │(URL)     │└────────┘         │
└─────────┘   └──────────┘   └──────────┘             ┌─────▼──────┐
                                        │   E-ink    │
                                        │  Display   │
                                        │ (Waveshare)│
                                        └────────────┘
```
