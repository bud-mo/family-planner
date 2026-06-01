# Family Planner — Agent Instructions

Questo file definisce le istruzioni sempre attive per tutti gli agenti AI che lavorano su questo repository. Si applica a ogni interazione nel workspace.

---

## Identità del Progetto

**Family Planner** è un'applicazione Python embedded per Raspberry Pi che visualizza un calendario su display HDMI o e-ink Waveshare. Include un server web FastAPI per configurazione e anteprima browser. Il rendering è basato su **Pillow** (PillowEinkRenderer): tutta la grafica è generata in Python nativo senza browser. Su HDMI la finestra è gestita da **pygame** (SDL); su e-ink l'immagine passa per un post-processor Pillow e viene inviata al pannello Waveshare via SPI. Il design segue l'estetica tipografica del *Wall Street Journal*: niente ombre, niente bordi arrotondati, niente animazioni.

---

## Stack e Versioni

| Componente | Tecnologia |
|---|
|---|
| Python | 3.11+ |
| Web server | FastAPI + Uvicorn |
| Template HTML | Jinja2 (solo `/config` e anteprima browser) |
| Rendering calendario | Pillow nativo (`PillowEinkRenderer`) — nessun browser |
| Post-processing e-ink | `EinkRenderer` — resize, quantizzazione palette, dithering Floyd-Steinberg |
| CalDAV | `caldav` + `icalendar` |
| Config | YAML + Pydantic v2 |
| Display HDMI | `pygame` (SDL) — finestra SDL, rendering diretto `PIL.Image` → surface |
| Display e-ink | Waveshare (import dinamico) |
| Target hardware | Raspberry Pi 3B+ / 4 / 5 |
| OS target | Raspberry Pi OS Lite Bookworm 64-bit |

---

## Convenzioni di Codice

### Python

- Stile: **PEP 8** rigoroso; formattazione con `black` (line length 100)
- Type hints obbligatori su tutte le funzioni pubbliche
- Docstring solo su classi e metodi pubblici non ovvi (stile Google)
- Usare `pathlib.Path` invece di `os.path` per tutti i percorsi file
- Usare `logging` standard (non `print`) per diagnostica runtime
- Gestione eccezioni esplicita: non usare `except Exception` naked — catturare tipi specifici
- Configurazione sempre validata tramite modelli **Pydantic v2** in `app/config.py`

### Sicurezza

- Le credenziali (password CalDAV, URL iCal segreti) non devono mai apparire in log, output API, o messaggi di errore
- **`GET /config`** azzera tutte le password tramite `_safe_config_dict` (includendo `server.auth_password`) — nessuna credenziale è restituita in chiaro
- **`GET /api/config/download`** restituisce un YAML sanitizzato — nessun segreto lascia il dispositivo via HTTP
- Le rotte `/config` e `/api/config/*` sono protette da **Basic Auth opzionale**: se `server.auth_username` e `server.auth_password` sono impostati, un confronto in tempo costante (`secrets.compare_digest`) blocca l'accesso non autenticato. Le rotte di anteprima (`/`, `/preview.png`, `/preview-eink.png`) restano sempre aperte
- Il file di configurazione YAML deve sempre avere permessi `600` sul dispositivo (verificato/corretto da `_check_file_permissions` in `config.py`)
- Usare App-Specific Password Apple per iCloud — mai la password dell'Apple ID
- Nessun secret hardcoded nel codice sorgente

### Import e Dipendenze

- Le librerie Waveshare **devono** essere importate dinamicamente, protette da `display.type == "eink"` — il codice deve girare su macOS/Linux senza le librerie hardware
- Pillow è il renderer primario (`PillowEinkRenderer`) per entrambi i display; `EinkRenderer` è solo post-processing e-ink
- Template HTML Jinja2 sono usati **solo** per la pagina `/config` e per l'anteprima browser (`GET /`) — non per il rendering del calendario
- HTMX è incluso come asset locale in `base.html` — non è un pacchetto pip, non va aggiunto a `requirements.txt`

---

## Architettura — Regole Invarianti

1. **Pipeline di rendering unificata**: `PillowEinkRenderer` è la fonte unica di rendering — `render(state, events)` → `PIL.Image` condiviso da HDMI ed e-ink. Non viene avviato alcun browser né processo Chromium.
2. **EinkRenderer** è solo post-processing: riceve un `PIL.Image` già composto e applica quantizzazione palette + dithering Floyd-Steinberg.
3. **FastAPI serve solo anteprima e configurazione**, mai il rendering del calendario via HTML/CSS. Rotte effettive: `GET /` (pagina HTML minimale con auto-refresh `<img src="/preview.png">`), `GET /preview.png` (chiama `PillowEinkRenderer.render()` on-demand), `GET /preview-eink.png` (anteprima con quantizzazione palette e-ink), `GET`/`POST /config`, `POST /api/test-weather`, `POST /api/test-connection`, `GET /api/config/download`, `POST /api/config/upload`.
4. **Riavvio graceful**: `POST /config` salva il file YAML e invia SIGHUP al processo (`_reload_config` in `main.py`) — non terminare il processo bruscamente. Il reload ricostruisce config, aggregator, weather provider, `PillowEinkRenderer` ed `EinkRenderer`; il display **non** viene riavviato.
5. **Vista Home unica, ancorata a oggi**: l'interfaccia è una sola schermata (banner meteo · mini-calendario · agenda · footer). Non esiste navigazione, paginazione né scroll; non esiste `StateManager` né rotta `/state`. `NavigationState` è un dataclass immutabile con il solo campo `anchor_date = date.today()`, ricreato a ogni render.
6. **Pulsanti fisici e tasti**: su e-ink Pimoroni Inky Impression i pulsanti sono **A = ritorno al planner**, **B = artwork (privacy)**, **D = spegnimento** (`InkyButtonHandler` → callback in `main.py`; il pulsante C non è acquisito perché in conflitto con SPI CS1). Su HDMI/pygame: tasto `B` mostra l'artwork, `D` avvia lo shutdown, `q`/`F4` chiudono. Nessuna dipendenza da Playwright o da click su DOM.
7. **Componenti con bounds espliciti**: ogni `_draw_*` di `PillowEinkRenderer` riceve il proprio `rect: Rect` come parametro. Il **calcolo della partizione dei `Rect`** (suddivisione di `W × H` fra banner/calendario/agenda/footer, per layout portrait e landscape) avviene **solo** in `render()`. I `_draw_*` possono leggere `self._layout` e costanti di sotto-componente (es. `BANNER_MAIN_HEIGHT`, `BANNER_HOURLY_HEIGHT`) per posizionare elementi interni, ma non ricalcolano la partizione globale.

---

## Design System — Vincoli per Template e Renderer

- **Unità di misura nel renderer**: usare esclusivamente `px` interi — nessun `rem`, `em`, valori float non arrotondati (display fisico a risoluzione fissa)
- **Nessuna ombra**: `box-shadow`, `text-shadow` e `drop-shadow` sono vietati (anche nelle pagine `/config`)
- **Nessun border-radius**: `border-radius: 0` ovunque
- **Nessuna transizione o animazione**: gli aggiornamenti sono istantanei
- **Font**: Playfair Display (headings) · IBM Plex Sans (body) · IBM Plex Mono (orari)
- **Icone**: Tabler Icons SVG outline, `stroke-width: 1.5px`, sempre `currentColor`
- **Palette**: 9 valori definiti in `docs/design.md` — non introdurre nuovi colori senza aggiornare la doc

---

## Workflow di Sviluppo

### Avvio locale

```bash
source .venv/bin/activate
python app/main.py --config config/config.yaml
```

Usare `display.type: "hdmi"` e `fullscreen: false` per sviluppo su macOS/Linux.

### Deploy su Raspberry Pi

```bash
./scripts/deploy.sh pi@<ip>           # copia i file via SSH
./scripts/setup-autostart.sh pi@<ip> # registra il servizio systemd
```

### Prima di ogni modifica

1. Leggere il file sorgente prima di editarlo
2. Verificare che le modifiche a `PillowEinkRenderer` producano output visivamente corretto per entrambi i display — fare screenshot via `GET /preview.png` sui `width`/`height` configurati
3. Validare le modifiche allo schema config contro i modelli Pydantic in `app/config.py`

### Dopo ogni modifica critica

Se la modifica tocca architettura, flusso dati, schema config, rotte API, design system o deploy, aggiornare **nella stessa sessione di lavoro**:

- `docs/architecture.md` — se cambia struttura, componenti, flusso o rotte
- `docs/design.md` — se cambia palette, tipografia, layout o design system
- `config/default.yaml` — se cambia lo schema di configurazione
- `AGENTS.md` — se cambiano le regole invarianti, le rotte o il modello di interazione (pulsanti/tasti)
- `README.md` — se cambiano funzionalità utente, configurazione o avvio

Non chiudere mai un task critico lasciando la documentazione non sincronizzata con il codice. `docs/architecture.md` è la fonte di verità: se diverge dal codice, allinearlo nella stessa sessione anziché crearne una copia.

---

## Documentazione di Riferimento

| File | Contenuto |
|---|---|
| `docs/architecture.md` | Stack, struttura progetto, flusso applicativo, rotte web |
| `docs/design.md` | Tipografia, palette, layout, schermate, interazioni |
| `docs/0.X.0-devplan.md` | Piani di sviluppo per versione (l'ultimo descrive il lavoro in corso/previsto) |
| `config/default.yaml` | Schema di configurazione con valori di default |
| `systemd/family-planner.service` | Unit file per il servizio systemd |
