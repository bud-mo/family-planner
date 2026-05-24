# Architettura — Family Planner Calendar

## Panoramica

**Family Planner** è un visualizzatore di calendario ottimizzato per dispositivi Raspberry Pi (3+) con display HDMI o e-ink, eseguibile anche in locale (Mac/Linux) per sviluppo e test. Espone un servizio web sia per la visualizzazione del calendario sia per la sua configurazione.

---

## Stack Tecnologico

| Layer | Tecnologia |
|---|---|
| Linguaggio | Python 3.11+ |
| Web server | FastAPI + Uvicorn |
| Template HTML | Jinja2 + HTMX (rendering calendario e configurazione) |
| Rendering calendario | Playwright (Chromium headless) — `PlaywrightRenderer.screenshot()` → `PIL.Image` |
| Post-processing e-ink | `EinkRenderer` — resize, quantizzazione palette, dithering |
| Calendario CalDAV | `caldav` + `icalendar` |
| Configurazione | YAML (`pyyaml`) + Pydantic v2 |
| Display HDMI | Playwright non-headless (Chromium) — finestra gestita da Python |
| Display e-ink | Waveshare (caricamento dinamico — richiede hardware RPi) |

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
│   │   ├── base.py                  # Classe astratta Renderer
│   │   ├── playwright_renderer.py   # PlaywrightRenderer: istanza Chromium persistente + screenshot() → PIL.Image
│   │   ├── eink_renderer.py         # Post-processing e-ink: resize, quantizzazione palette, dithering
│   │   ├── state.py                 # NavigationState (dataclass immutabile) + View enum
│   │   └── tokens.py                # Design tokens Python — sincronizzati con CSS custom properties in base.html
│   └── display/
│       ├── __init__.py
│       ├── hdmi.py              # HdmiDisplay: apre finestra Playwright non-headless
│       └── eink.py              # EinkDisplay: push immagine via SPI (libreria Waveshare)
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
  type: "hdmi"               # "hdmi" | "eink"
  width: 1920
  height: 1080
  fullscreen: false          # true → finestra kiosk; false → finestra dimensionata (sviluppo)
  refresh_interval: 300      # secondi tra un aggiornamento e l'altro
  show_buttons: false        # mostra/nasconde i pulsanti di navigazione a schermo
  playwright_executable: null # percorso Chromium di sistema (null = usa bundle Playwright)
  # solo se type: "eink":
  eink_dither: true          # abilita dithering: true (Floyd-Steinberg) | "atkinson" (migliore per Spectra 6)

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
  Avvia FastAPI / Uvicorn (thread daemon)
  ├─── GET /          ──▶  Rendering calendario (Jinja2 + HTMX) — fonte unica per tutti i display
  ├─── GET /state     ──▶  Stato navigazione corrente come JSON
  ├─── POST /state    ──▶  Aggiorna stato navigazione (azione: next/prev/in/out/night)
  ├─── GET /config    ──▶  Mostra form di configurazione
  └─── POST /config   ──▶  Salva config.yaml → Riavvio graceful
        │
        ▼
  Avvia PlaywrightRenderer
  (istanza Chromium persistente — headless per e-ink, non-headless per HDMI)
        │
        ▼
  Avvia Display
        │
        ├── HDMI ──▶  HdmiDisplay.start() apre finestra Playwright non-headless
        │             puntando a http://localhost:{port}/
        │             HTMX gestisce gli aggiornamenti DOM senza full-page reload
        │
        └── E-ink ──▶  Loop daemon (ogni refresh_interval):
                        PlaywrightRenderer.screenshot() → PIL.Image
                        EinkRenderer: resize → quantize palette → dither
                        EinkDisplay.push() → SPI → pannello Waveshare
```

---

## Rotte Web

### `GET /`
Rendering calendario (Jinja2 + HTMX). **È la sorgente unica di rendering**: `PlaywrightRenderer` acquisisce screenshot di questa rotta per alimentare sia il display HDMI sia il display e-ink.

Accetta il parametro opzionale `?view=annual|monthly|weekly|daily|detail` per selezionare la vista. Se omesso, viene usata la vista corrente dal `NavigationState`.

I pulsanti di navigazione sono sempre presenti nel DOM; la loro visibilità è controllata da `show_buttons` nella configurazione.

### `GET /state`
Restituisce il `NavigationState` corrente come JSON:
```json
{
  "view": "weekly",
  "selected_date": "2026-05-23",
  "selected_event_uid": null,
  "detail_scroll_offset": 0,
  "night_mode": false
}
```

### `POST /state`
Applica un'azione di navigazione e restituisce il nuovo stato. Accetta `{"action": "prev"|"next"|"in"|"out"|"night"}`. Consente a script GPIO, tastiera fisica o automazioni di controllare la navigazione senza accedere al processo display direttamente.

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

### Architettura generale

Il rendering del calendario è prodotto da **`PlaywrightRenderer`** che mantiene un'istanza Chromium persistente puntata alla rotta `GET /` di FastAPI e cattura screenshot come `PIL.Image`. HDMI ed e-ink condividono la stessa fonte HTML; differiscono solo nel modo in cui consumano il `PIL.Image`:

```
FastAPI + Jinja2 + HTMX  →  GET /  →  HTML
                                  │
                        PlaywrightRenderer
                        (Chromium persistente)
                        page.screenshot() → PIL.Image
                                  │
              ┌───────────────────┴───────────────────┐
              │                                       │
    (HDMI) Playwright non-headless          (E-ink) EinkRenderer
    finestra visibile a schermo             → resize alla risoluzione del pannello
    HTMX gestisce la navigazione            → quantizzazione palette (B&W / BWR / 4gray)
    senza full-page reload                  → dithering Floyd-Steinberg (opzionale)
                                                       ↓
                                            EinkDisplay (eink.py)
                                            → push via SPI (Waveshare driver)
```

### Navigazione e stato

Lo stato di navigazione è gestito da **`NavigationState`** (`renderer/state.py`) — un dataclass immutabile che vive all'interno del `PlaywrightRenderer`. Tutti i metodi `navigate_*()` restituiscono una nuova istanza; `PlaywrightRenderer.update_state()` sostituisce atomicamente lo stato corrente con un lock threading.

```
Input touchscreen / pulsante a schermo
  o GPIO fisico (RPi)
  o POST /state via HTTP (script esterno)
        │
        ▼
  playwright_renderer.get_state()  →  NavigationState corrente
  state.navigate_*(events)          →  nuovo NavigationState
  playwright_renderer.update_state(new_state)
        │
        ▼
  HTMX aggiorna il DOM: GET / → Jinja2 → HTML aggiornato
  (HDMI: il pulsante HTMX aggiorna la pagina aperta)
  (E-ink: il loop daemon chiama page.reload() → screenshot() al prossimo ciclo)
```

**GPIO → Playwright click**: il gestore GPIO chiama `page.click('#btn-nav-next')` (o `prev`, `in`, `out`, `night`). Il pulsante HTML nascosto ha un attributo HTMX che invia `POST /state` — identico al click touchscreen.

Il server web espone `GET /state` e `POST /state` per consentire a script GPIO o sessioni di debug di leggere e modificare lo stato senza accedere al processo display direttamente.

### HDMI — Playwright non-headless

`display/hdmi.py` avvia un'istanza Playwright non-headless puntando a `http://localhost:{port}/`.

**Avvio:**
```
HdmiDisplay.start()
  → poll HTTP GET / fino a risposta 200 (timeout 30 s)
  → playwright.chromium.launch(headless=False, executable_path=config.playwright_executable)
  → browser.new_page() → page.goto('http://localhost:{port}/')
```

**Aggiornamento del display**: HTMX gestisce la navigazione senza full-page reload. Il `PlaywrightRenderer` chiama `page.evaluate()` per triggerare gli aggiornamenti o usa `page.click()` sui pulsanti HTMX nascosti.

**Modalità kiosk** (`fullscreen: true`): Playwright apre la finestra a schermo intero — nessun flag shell necessario, gestito via `browser_context` options.

**Modalità sviluppo** (`fullscreen: false`): finestra dimensionata `width × height` dalla configurazione.

**Executable**: configurabile via `playwright_executable`. Default: bundle Playwright. Su RPi: `/usr/bin/chromium-browser` (evita ~300 MB overhead del bundle).

**Su Raspberry Pi**: Playwright non-headless richiede un display server. Aggiungere `After=graphical.target` e le variabili `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR` nel service systemd per Wayland, oppure `DISPLAY=:0` per X11.

### E-ink — Playwright headless + post-processing Pillow

`display/eink.py` esegue un loop daemon con intervallo `refresh_interval`. Ad ogni iterazione:

1. **`PlaywrightRenderer.screenshot()`** esegue `page.reload()` e cattura uno screenshot della pagina `GET /` come `PIL.Image` RGB alle dimensioni configurate. Il browser Chromium è mantenuto in sessione persistente — non viene rilanciato ad ogni ciclo.
2. **`EinkRenderer`** (`renderer/eink_renderer.py`) applica:
   - **Ridimensionamento** alla risoluzione nativa del pannello (13 modelli Waveshare supportati)
   - **Quantizzazione palette**: B&W (1 bit), BWR (3 colori), 4-gray — configurabile via `eink_palette`
   - **Dithering Floyd-Steinberg** — opzionale, via `eink_dither: true`
3. **`EinkDisplay`** (`display/eink.py`) invia l'immagine al pannello via il driver Waveshare appropriato, caricato dinamicamente:
   ```python
   # Import protetto — si attiva solo quando display.type == "eink"
   from waveshare_epd import epd13in3k  # esempio modello 13.3"
   ```
   Questo garantisce che il codice sia eseguibile su macOS/Linux senza le librerie hardware.

> **Pannelli supportati**: tutti i modelli Waveshare con driver Python disponibile — la mappatura `eink_model → modulo` è in `display/eink.py`.

> **Refresh time**: i pannelli e-ink Waveshare impiegano tipicamente 15–30 secondi per un aggiornamento completo. Impostare `refresh_interval` ≥ 60 secondi.

> **Su RPi**: il loop e-ink non richiede un display server — funziona su RPi OS Lite senza X11 o Wayland.

---

## Multipiattaforma

| Comportamento | Mac (sviluppo) | Linux / Raspberry Pi (produzione) |
|---|---|---|
| `display.fullscreen: false` | Playwright non-headless, finestra `width × height` | Playwright non-headless, finestra `width × height` |
| `display.fullscreen: true` | Playwright non-headless, schermo intero | Playwright non-headless, kiosk + Wayland/X11 |
| `playwright_executable` | `null` (bundle Playwright) | `/usr/bin/chromium-browser` (sistema RPi) |
| Display e-ink | Playwright headless; driver Waveshare non caricato (stub silenzioso) | Playwright headless; driver Waveshare via SPI |
| Calendario | CalDAV / ICS / iCal via rete o file locale | CalDAV / ICS / iCal via rete o file locale |
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
- Installa dipendenze di sistema (`python3-pip`, `chromium-browser`, librerie SPI per e-ink)
- Crea il virtualenv
- Installa i pacchetti Python da `requirements.txt`
- Copia il file systemd in `/etc/systemd/system/`

### `scripts/setup-autostart.sh`
- Abilita e avvia il servizio systemd:
  - `family-planner.service` — server Python + gestione display (tutto in un unico processo)
- Per display HDMI: imposta le variabili d'ambiente Wayland (`WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR`) o X11 (`DISPLAY`) nel service
- Per display e-ink: nessun display server richiesto

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
ExecStart=/home/pi/family-planner/venv/bin/python app/main.py --config /home/pi/family-planner/config.yaml
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

> **Nota HDMI**: Per la modalità HDMI con Chromium su RPi con Wayland, aggiungere `After=graphical.target` e le variabili `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR` (o `DISPLAY=:0` per X11) nell'environment del service. Per la modalità e-ink non è necessario alcun display server.

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
evaltype-backport          # compatibilità type hints Python 3.9
pyyaml
caldav
requests                   # HTTP per iCal URL provider
icalendar
pillow                     # post-processing e-ink (EinkRenderer) — non usato per rendering calendario
playwright                 # rendering calendario via Chromium headless/non-headless
# playwright install chromium  # da eseguire dopo pip install; oppure usare playwright_executable
# htmx                    # incluso come asset locale in base.html — non è un pacchetto pip
# chromium-browser         # Chromium di sistema su RPi (alternativa al bundle Playwright)
python-multipart           # form POST /config
# waveshare-epaper (opzionale — solo su RPi con display e-ink)
```

---

## Diagramma Componenti

```
┌──────────────────────────────────────────────────────────────┐
│                          main.py                             │
│   args parsing → config load → aggregator → playwright_rend │
└────────────┬─────────────────────────────┬───────────────────┘
             │                             │
     ┌───────▼──────┐          ┌───────────▼──────────────┐
     │  FastAPI App  │          │    PlaywrightRenderer    │
     │  GET /        │◀─────────│    (Chromium persistente)│
     │  GET /state   │  punta a │    NavigationState       │
     │  POST /state  │  GET /   │    + threading.Lock      │
     │  GET /config  │          └──────────┬───────────────┘
     │  POST /config │                     │ PIL.Image (screenshot)
     └───────┬───────┘          ┌──────────┴──────────┐
             │                  │                     │
     ┌───────▼──────┐  ┌────────▼──────┐  ┌──────────▼──────┐
     │  Aggregator  │  │  HdmiDisplay  │  │  EinkRenderer   │
     │  (calendari) │  │  Playwright   │  │  resize/quantize│
     └───────┬───────┘  │  non-headless │  │  dither         │
             │          └───────────────┘  └──────────┬──────┘
    ┌────────┴────────┐                               │ PIL.Image
    │                 │                      ┌────────▼─────┐
┌───▼────┐  ┌─────────▼──┐  ┌────────┐      │  EinkDisplay │
│ CalDAV │  │    ICS     │  │  iCal  │      │  (Waveshare) │
│Provider│  │  Provider  │  │Provider│      │  SPI / RPi   │
└────────┘  └────────────┘  └────────┘      └──────────────┘
```
