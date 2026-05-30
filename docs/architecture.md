# Architettura — Family Planner Calendar

## Panoramica

**Family Planner** è un visualizzatore di calendario ottimizzato per dispositivi Raspberry Pi (3+) con display HDMI o e-ink, eseguibile anche in locale (Mac/Linux) per sviluppo e test. Espone un servizio web sia per la visualizzazione del calendario sia per la sua configurazione.

---

## Stack Tecnologico

| Layer | Tecnologia |
|---|---|
| Linguaggio | Python 3.11+ |
| Web server | FastAPI + Uvicorn |
| Template HTML | Jinja2 (solo configurazione) |
| Rendering (HDMI + e-ink) | `PillowEinkRenderer` — Pillow nativo da `NavigationState` + eventi, senza browser |
| Post-processing e-ink | `EinkRenderer` — resize, quantizzazione palette, dithering Floyd-Steinberg |
| Calendario CalDAV | `caldav` + `icalendar` |
| Configurazione | YAML (`pyyaml`) + Pydantic v2 |
| Display HDMI | `pygame` — finestra SDL, rendering diretto `PIL.Image` → surface |
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
│   │   │   ├── index.py         # GET / — anteprima HTML; GET /preview.png — immagine PNG
│   │   │   └── config.py        # GET/POST /config — configurazione UI
│   │   └── templates/           # Template Jinja2
│   │       ├── base.html        # Layout base configurazione
│   │       └── config.html      # Interfaccia configurazione
│   ├── calendar/
│   │   ├── __init__.py
│   │   ├── base.py              # Classe astratta CalendarProvider
│   │   ├── caldav_provider.py   # Provider CalDAV (Apple Calendar / iCloud)
│   │   ├── ics_provider.py      # Provider file .ics locali
│   │   ├── ical_provider.py     # Provider iCal URL (Google Calendar, feed pubblici)
│   │   ├── aggregator.py        # Aggrega eventi da più provider
│   │   └── data_builders.py     # Preparazione dati condivisa tra rotte e PillowEinkRenderer
│   ├── renderer/
│   │   ├── __init__.py
│   │   ├── base.py                      # Classe astratta Renderer
│   │   ├── pillow_eink_renderer.py      # PillowEinkRenderer: rendering Pillow nativo (HDMI + e-ink)
│   │   ├── eink_renderer.py             # Post-processing e-ink: resize, quantizzazione palette, dithering
│   │   ├── rich_text.py                 # Parser HTML descrizioni CalDAV → RichSpan/RichLine
│   │   ├── state.py                     # NavigationState (dataclass immutabile — anchor_date = oggi)
│   │   └── tokens.py                    # Design tokens Python
│   ├── weather/
│   │   ├── __init__.py
│   │   ├── provider.py          # WeatherProvider: classe base astratta
│   │   └── open_meteo.py        # OpenMeteoProvider: API Open-Meteo + cache in-memory TTL 1h
│   └── display/
│       ├── __init__.py
│       ├── hdmi.py              # HdmiDisplay: finestra pygame — rendering PIL.Image diretto
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

weather:
  enabled: true              # false → disabilita il provider, mostra solo la data
  latitude: 45.4654          # coordinate GPS della posizione
  longitude: 9.1866
  units: "celsius"           # "celsius" | "fahrenheit"

display:
  type: "hdmi"               # "hdmi" | "eink"
  layout: "landscape"        # "landscape" | "portrait"
  width: 1024
  height: 600
  width: 1024
  height: 600
  fullscreen: false          # true → finestra fullscreen; false → finestra dimensionata (sviluppo)
  refresh_interval: 300      # secondi tra un aggiornamento e l'altro
  show_buttons: false        # mostra/nasconde i pulsanti di navigazione (solo HDMI touchscreen)
  # solo se type: "eink":
  eink_dither: true          # abilita dithering Floyd-Steinberg

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

> **Nota sicurezza**: il file di configurazione non contiene credenziali meteo (Open-Meteo non richiede API key). Le coordinate GPS sono considerate dati non sensibili in questo contesto.

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
  Inizializza OpenMeteoProvider  ← solo se weather.enabled: true
  (cache in-memory TTL 1h, thread-safe)
        │
        ▼
  Inizializza PillowEinkRenderer(config, weather_provider)  ← renderer unico per HDMI ed e-ink
        │
        ▼
  Avvia Display (condizionale sul tipo)
        │
        ├── HDMI ──▶  HdmiDisplay(config, pillow_renderer, aggregator)
        │             Uvicorn avviato in background thread
        │             ├─── GET /             ──▶  HTML anteprima (img auto-refresh)
        │             ├─── GET /preview.png  ──▶  PillowEinkRenderer.render() → PNG
        │             ├─── GET /config       ──▶  Mostra form di configurazione
        │             └─── POST /config      ──▶  Salva config.yaml → SIGHUP
        │             HdmiDisplay.run_blocking() blocca il main thread con pygame:
        │               loop: NavigationState() → PillowEinkRenderer.render()
        │                     → pygame.Surface → schermo
        │               tasti: q/F4 quit
        │
        └── E-ink ──▶  PillowEinkRenderer(config)  [nessun browser, nessun display server]
                        Uvicorn sul main thread
                        Loop daemon (ogni refresh_interval):
                          NavigationState() → anchor_date = oggi
                          aggregator.get_events(start, end) → eventi
                          PillowEinkRenderer.render(state, events) → PIL.Image
                          EinkRenderer.process(img) → palette quantizzata
                          EinkDisplay.push() → SPI → pannello Waveshare
```

---

## Rotte Web

### `GET /`
Pagina HTML minimale con auto-refresh che mostra l'immagine calendario corrente via `<img src="/preview.png">`. L'intervallo di refresh è pari a `display.refresh_interval` secondi. Utile per anteprima browser durante lo sviluppo.

### `GET /preview.png`
Chiama `PillowEinkRenderer.render(state, events)` on-demand e restituisce l'immagine PNG risultante (`Content-Type: image/png`). È la stessa immagine che verrebbe inviata al pannello e-ink.

### `GET /config`
Interfaccia web per la configurazione: aggiunta/rimozione calendari, modifica parametri di visualizzazione, test della connessione ai provider.

### `POST /config`
Salva le modifiche nel file di configurazione e riavvia il server in modo graceful (SIGHUP o riavvio Uvicorn).

---

## Integrazione Meteo — Open-Meteo

Il meteo è fornito da **Open-Meteo** (`https://api.open-meteo.com`) — API pubblica, gratuita, senza API key, GDPR-compliant, con aggiornamenti ogni ora.

### Modulo `app/weather/`

```
app/weather/
├── __init__.py          # esporta WeatherProvider, OpenMeteoProvider
├── provider.py          # WeatherProvider: ABC thread-safe — get() → WeatherData
└── open_meteo.py        # OpenMeteoProvider: fetch + cache in-memory TTL 1h
```

### API endpoint

```
GET https://api.open-meteo.com/v1/forecast
    ?latitude=<lat>
    &longitude=<lon>
    &current=temperature_2m,weather_code
    &daily=temperature_2m_max,temperature_2m_min
    &temperature_unit=celsius
    &timezone=auto
    &forecast_days=1
```

### Cache in-memory

`OpenMeteoProvider` mantiene una cache in-memory protetta da `threading.Lock`:
- Il campo `_cached_at` registra il timestamp dell'ultimo fetch (`time.monotonic()`)
- Se `now − cached_at < 3600s` e i dati sono presenti, viene restituita la cache senza chiamate di rete
- Il fetch HTTP avviene **fuori dal lock** (`timeout=10s`) per non bloccare il thread di rendering
- In caso di errore HTTP/parse, la cache stale è restituita; se non esiste ancora nessuna cache, viene restituito `WeatherData()` vuoto → il renderer mostra solo la data

### Struttura `WeatherData` (`renderer/tokens.py`)

```python
@dataclass
class WeatherData:
    condition_icon: str | None = None   # nome icona Tabler (es. "sun", "cloud-rain")
    description: str | None = None      # testo italiano (es. "Sereno", "Pioggia")
    temp_current: float | None = None   # temperatura attuale
    temp_max: float | None = None       # massima giornaliera
    temp_min: float | None = None       # minima giornaliera
```

### Mappatura WMO 4677 → icone Tabler

| Codici WMO | Condizione | Icona Tabler |
|---|---|---|
| 0, 1 | Sereno / Prevalentemente sereno | `sun` |
| 2, 3, 45, 48 | Nuvoloso / Nebbia | `cloud` |
| 51–67, 80–82, 95–99 | Pioggia / Rovesci / Temporale | `cloud-rain` |
| 56, 57, 66, 67, 71–77, 85, 86 | Neve / Gelate | `snowflake` |

Le icone PNG corrispondenti (`{nome}.png`, 24×24 px) devono essere presenti in `app/assets/icons/weather/`. Se il file manca, il renderer usa il campo `description` come testo alternativo. Se entrambi mancano, la zona destra del banner mostra solo la temperatura.

### Rendering nel banner

`_draw_weather()` segue questa priorità per la zona destra del banner:
1. **Icona PNG** (se `condition_icon` è impostato e il file `app/assets/icons/weather/{icon}.png` esiste): 24×24 px, tintato con `palette["INK"]`, posizionato a sinistra della temperatura.
2. **Testo description** (fallback se PNG mancante): resa in `--text-xs` / `INK_MUTED`, allineata a destra della temperatura.
3. **Solo temperatura** (se `WeatherData` è vuoto): comportamento attuale — solo la data è mostrata se anche la temperatura è `None`.

### Degradazione graceful

In tutti i casi di errore (rete assente, API irraggiungibile, risposta malformata), `OpenMeteoProvider.get()` non rilancia eccezioni: restituisce la cache stale se disponibile, altrimenti `WeatherData()` vuoto. Il rendering non viene mai bloccato dalla mancanza di dati meteo.

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

Family Planner adotta un **renderer unico** — `PillowEinkRenderer` — condiviso da HDMI ed e-ink. Non viene avviato alcun browser né processo Chromium.

```
           NavigationState() — sempre oggi
                    │
   PillowEinkRenderer (HDMI + e-ink)
   Pillow nativo — render(state, events)
   → PIL.Image
          │
   ┌──────┴──────┐                    ┌──────────────────┐
   │ HdmiDisplay │                    │   EinkRenderer   │
   │  (pygame)   │                    │ resize/quantize  │
   │ main thread │                    │ dither           │
   │ SDL window  │                    └─────────┬────────┘
   └─────────────┘                             │ PIL.Image quantizzata
                                    ┌──────────▼─────────┐
                                    │    EinkDisplay      │
                                    │    (Waveshare SPI)  │
                                    └────────────────────┘
```

### HDMI — pygame

`display/hdmi.py` apre una finestra SDL tramite `pygame` e renderizza direttamente l'immagine `PIL.Image` prodotta da `PillowEinkRenderer`.

**Thread model**: su macOS SDL/Cocoa deve girare sul main thread. Per questo motivo:
- `HdmiDisplay.run_blocking()` esegue il loop pygame sul thread chiamante (main thread)
- Uvicorn gira in un background thread (`threading.Thread`)

**Loop pygame:**
```
run_blocking()
  → pygame.init() → display.set_mode(width × height)
  loop ogni ~100 ms:
    NavigationState() → PillowEinkRenderer.render(state, events) → pygame.Surface
    pygame.display.flip()
    eventi tastiera: q/F4 quit
```

**Re-render**: allo scadere di `refresh_interval` secondi (aggiornamento dati calendario) o al cambio di data a mezzanotte.

**Modalità fullscreen** (`fullscreen: true`): `pygame.FULLSCREEN | pygame.NOFRAME` — nessun flag shell necessario.

**Modalità sviluppo** (`fullscreen: false`): finestra dimensionata `width × height` dalla configurazione.

**Su Raspberry Pi con Wayland**: impostare le variabili `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR` nell'environment del service systemd. Con X11: `DISPLAY=:0`.

### E-ink — PillowEinkRenderer (Pillow nativo, senza browser)

Il loop e-ink non avvia alcun processo Chromium. Il rendering avviene interamente in-process tramite **`PillowEinkRenderer`** (`renderer/pillow_eink_renderer.py`), che produce un `PIL.Image` direttamente da `NavigationState` e dalla lista eventi. I font TTF sono caricati da `app/assets/fonts/` — nessuna chiamata di rete.

`main.py` avvia un thread daemon che esegue ogni `refresh_interval` secondi:

1. **`NavigationState()`** crea un nuovo stato con `anchor_date = date.today()`.
2. **`aggregator.get_events(start, end)`** recupera gli eventi per l'intervallo della vista corrente.
3. **`PillowEinkRenderer.render(state, events)`** produce un `PIL.Image` RGB nelle dimensioni configurate (`display.width × display.height`).
4. **`EinkRenderer`** (`renderer/eink_renderer.py`) applica:
   - **Ridimensionamento** alla risoluzione nativa del pannello (13 modelli Waveshare supportati)
   - **Quantizzazione palette**: B&W (1 bit), BWR (3 colori), 4-gray — configurabile via `eink_palette`
   - **Dithering Floyd-Steinberg** — opzionale, via `eink_dither: true`
5. **`EinkDisplay`** (`display/eink.py`) invia l'immagine al pannello via il driver Waveshare appropriato, caricato dinamicamente:
   ```python
   # Import protetto — si attiva solo quando display.type == "eink"
   from waveshare_epd import epd13in3k  # esempio modello 13.3"
   ```
   Questo garantisce che il codice sia eseguibile su macOS/Linux senza le librerie hardware.

> **Pannelli supportati**: tutti i modelli Waveshare con driver Python disponibile — la mappatura `eink_model → modulo` è in `display/eink.py`.

> **Refresh time**: i pannelli e-ink Waveshare impiegano tipicamente 15–30 secondi per un aggiornamento completo. Impostare `refresh_interval` ≥ 60 secondi.

> **Su RPi**: il loop e-ink non richiede un display server — funziona su RPi OS Lite senza X11 o Wayland. Con `display.type: "eink"`, `pygame` non viene mai importato.

### Schermata Home — Unica Vista

L'interfaccia è costituita da un'**unica schermata Home** — non esiste gerarchia di viste né navigazione. Il `NavigationState` porta un solo campo: `anchor_date = date.today()`, usato per determinare il mese del mini-calendario e la finestra di 30 giorni della lista appuntamenti.

`PillowEinkRenderer.render(state, events)` delega a quattro componenti, ognuno ricevendo il proprio `Rect`:

| Componente | Metodo | `Rect` (portrait) | `Rect` (landscape) |
|---|---|---|---|
| Banner meteo | `_draw_weather()` | `(0, 0, W, 90)` | `(0, 0, col_left, 90)` |
| Mini-calendario | `_draw_mini_calendar()` | `(0, 90, W, 250)` | `(0, 90, col_left, H−130)` |
| Lista appuntamenti | `_draw_agenda()` | `(0, 340, W, H−380)` | `(col_left, 0, col_right, H−40)` |
| Footer | `_draw_footer()` | `(0, H−40, W, 40)` | `(0, H−40, W, 40)` |

dove `col_left = int(W × 0.38)` e `col_right = W − col_left`.

> **Componente meteo**: la struttura `WeatherData` (icona condizione, descrizione testuale, temperatura attuale, max/min giornalieri) è prodotta da `OpenMeteoProvider.get()` — chiamata dentro `PillowEinkRenderer.render()` se il provider è stato iniettato. In assenza di provider (o se `weather.enabled: false`), `WeatherData` rimane vuota e il banner mostra solo la data.

---

## Architettura Componenti Grafici — Bounds Espliciti

Ogni componente `_draw_*` di `PillowEinkRenderer` riceve i propri limiti di disegno come parametro esplicito `rect: Rect`. Non legge costanti di layout globali al proprio interno.

### Tipo `Rect`

```python
# renderer/tokens.py
Rect = tuple[int, int, int, int]  # (x, y, width, height)
```

### Regola fondamentale

`render()` è il **solo** punto dell'intera codebase dove si calcolano i `Rect` di layout, a partire dalle dimensioni del display (`W × H`) e dalla variante (`display.layout`). Le costanti `BANNER_HEIGHT`, `CALENDAR_HEIGHT`, `FOOTER_HEIGHT`, `COL_LEFT_RATIO` compaiono **esclusivamente** in `render()` — mai nei metodi `_draw_*`.

### Firme dei componenti Home

```python
BannerHeight   = 90
CalendarHeight = 250
FooterHeight   = 40
ColLeftRatio   = 0.38

def _draw_weather(
    self, draw: ImageDraw, rect: Rect,
    weather: WeatherData, palette: dict
) -> None: ...

def _draw_mini_calendar(
    self, draw: ImageDraw, rect: Rect,
    state: NavigationState, events: list, palette: dict
) -> None: ...

def _draw_agenda(
    self, draw: ImageDraw, rect: Rect,
    state: NavigationState, events: list, palette: dict
) -> None: ...

def _draw_footer(
    self, draw: ImageDraw, rect: Rect,
    palette: dict
) -> None: ...
```

### Calcolo dei `Rect` in `render()`

```python
def render(self, state: NavigationState, events: list) -> Image.Image:
    W, H = self._size
    palette = get_palette()
    img = Image.new("RGB", (W, H), palette["BG"])
    draw = ImageDraw.Draw(img)

    if self._layout == "portrait":
        weather_rect   = (0,        0,       W,          BANNER_HEIGHT)
        calendar_rect  = (0,        BANNER_HEIGHT, W,    CALENDAR_HEIGHT)
        agenda_rect    = (0,        BANNER_HEIGHT + CALENDAR_HEIGHT,
                          W,        H - BANNER_HEIGHT - CALENDAR_HEIGHT - FOOTER_HEIGHT)
        footer_rect    = (0,        H - FOOTER_HEIGHT, W, FOOTER_HEIGHT)
    else:  # landscape
        col_left  = int(W * COL_LEFT_RATIO)
        col_right = W - col_left
        weather_rect   = (0,        0,       col_left,   BANNER_HEIGHT)
        calendar_rect  = (0,        BANNER_HEIGHT, col_left,
                          H - BANNER_HEIGHT - FOOTER_HEIGHT)
        agenda_rect    = (col_left, 0,       col_right,  H - FOOTER_HEIGHT)
        footer_rect    = (0,        H - FOOTER_HEIGHT, W, FOOTER_HEIGHT)

    self._draw_weather(draw, weather_rect, weather_data, palette)
    self._draw_mini_calendar(draw, calendar_rect, state, events, palette)
    self._draw_agenda(draw, agenda_rect, state, events, palette)
    self._draw_footer(draw, footer_rect, palette)
    return img
```

### Coordinate assolute nei componenti

All'interno di ogni `_draw_*`, le coordinate assolute sul canvas si ricavano sempre dall'origine del `rect` ricevuto:

```python
x0, y0, w, h = rect
# disegno di un testo a (local_x, local_y) relativo al componente:
draw.text((x0 + local_x, y0 + local_y), text, font=font, fill=color)
```

### Benefici

- **Testabilità**: ogni componente è esercitabile su un canvas di dimensioni arbitrarie, senza configurazione globale del display.
- **Separazione di responsabilità**: il layout vive solo in `render()`; i componenti non conoscono la struttura globale.
- **Estensibilità**: aggiungere un nuovo componente o variante di layout richiede solo un nuovo `Rect` in `render()` e un nuovo metodo `_draw_*`.

### Scope del Refactoring

Riguarda **esclusivamente** `PillowEinkRenderer` (`renderer/pillow_eink_renderer.py`) e l'aggiunta di `Rect` + costanti rinominate in `renderer/tokens.py`. I provider calendario e FastAPI non sono coinvolti.

---

## Multipiattaforma

| Comportamento | Mac (sviluppo) | Linux / Raspberry Pi (produzione) |
|---|---|---|
| `display.fullscreen: false` | pygame, finestra `width × height` | pygame, finestra `width × height` |
| `display.fullscreen: true` | pygame fullscreen (SDL) | pygame fullscreen + Wayland/X11 |
| Thread model HDMI | pygame sul main thread, Uvicorn in bg thread | idem |
| Display e-ink | PillowEinkRenderer (Pillow nativo); driver Waveshare non caricato | PillowEinkRenderer (Pillow nativo); driver Waveshare via SPI |
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
- Installa dipendenze di sistema (`python3-pip`, `python3-pygame`, librerie SPI per e-ink)
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

> **Nota HDMI**: Per la modalità HDMI con pygame su RPi con Wayland, aggiungere `After=graphical.target` e le variabili `WAYLAND_DISPLAY` / `XDG_RUNTIME_DIR` (o `DISPLAY=:0` per X11) nell'environment del service. Per la modalità e-ink non è necessario alcun display server.

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
eval_type_backport         # compatibilità type hints Python 3.9
pyyaml
caldav
requests                   # HTTP per iCal URL provider + Open-Meteo weather API
icalendar
pillow                     # renderer unico (PillowEinkRenderer) + post-processing (EinkRenderer)
pygame                     # display HDMI — finestra SDL, rendering PIL.Image diretto
python-multipart           # form POST /config
# waveshare-epaper (opzionale — solo su RPi con display e-ink)
```

---

## Diagramma Componenti

```
┌───────────────────────────────────────────────────────────────────────┐
│                             main.py                                   │
│  args parsing → config load → StateManager → aggregator → renderer   │
└──────┬────────────────────────────┬───────────────────────┬───────────┘
       │                            │                       │
┌──────▼──────┐           ┌─────────▼──────────┐  ┌────────▼────────┐
│  FastAPI    │           │   StateManager     │  │   Aggregator    │
│  GET /      │◀──────────│   (thread-safe)    │  │   (calendari)   │
│  GET /prev. │  legge /  │   NavigationState  │  └────────┬────────┘
│  POST /state│  scrive   │   threading.Lock   │    ┌──────┴──────┐
│  GET /config│   stato   └─────────┬──────────┘    │             │
│  POST/config│                     │            ┌──▼──┐  ┌───────▼────┐
└─────────────┘                     │            │CalDAV│  │  ICS/iCal  │
                                    │            │Prov. │  │  Provider  │
                          ┌─────────▼──────────┐ └──────┘  └────────────┘
                          │  PillowEinkRenderer │
                          │  (HDMI + e-ink)     │◀──── OpenMeteoProvider
                          │  Pillow nativo      │      cache in-memory
                          │  state + events     │      TTL 1h
                          │  + WeatherData      │      (opzionale)
                          └─────────┬───────────┘
                                    │ PIL.Image
               ┌────────────────────┴─────────────────────┐
               │                                          │
    ┌──────────▼────────┐                    ┌────────────▼───────┐
    │   HdmiDisplay     │                    │    EinkRenderer    │
    │   pygame window   │                    │    resize/quantize │
    │   (main thread)   │                    │    dither          │
    └───────────────────┘                    └────────────┬───────┘
                                                          │ PIL.Image quantizzata
                                             ┌────────────▼───────┐
                                             │    EinkDisplay      │
                                             │    (Waveshare SPI)  │
                                             └────────────────────┘
```
