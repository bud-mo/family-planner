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

- Le credenziali CalDAV non devono mai apparire in log, output API, o messaggi di errore
- Il file di configurazione YAML deve sempre avere permessi `600` sul dispositivo
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
3. **FastAPI serve solo `/config` e `/preview.png`**: `GET /` restituisce una pagina HTML minimale con auto-refresh (`<img src="/preview.png">`); `GET /preview.png` chiama `PillowEinkRenderer.render()` on-demand. Il rendering del calendario non passa mai per HTML/CSS.
4. **Riavvio graceful**: `POST /config` salva il file YAML e riavvia Uvicorn con SIGHUP — non terminare il processo bruscamente.
5. **Nessun scroll** nel layout — la paginazione Su/Giù sostituisce l'intera pagina.
6. **GPIO e tastiera pygame usano lo stesso meccanismo**: `POST /state` con `action = prev|next|today|night` — nessuna dipendenza da Playwright o click su elementi DOM.
7. **Componenti con bounds espliciti**: ogni `_draw_*` di `PillowEinkRenderer` riceve `rect: Rect` come parametro esplicito. `render()` è il solo punto dove si calcolano i `Rect`. I metodi `_draw_*` non leggono mai `BANNER_HEIGHT`, `CALENDAR_HEIGHT` o altre costanti di layout globali direttamente.

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

Non chiudere mai un task critico lasciando la documentazione non sincronizzata con il codice.

---

## Documentazione di Riferimento

| File | Contenuto |
|---|---|
| `docs/architecture.md` | Stack, struttura progetto, flusso applicativo, rotte web |
| `docs/design.md` | Tipografia, palette, layout, schermate, interazioni |
| `config/default.yaml` | Schema di configurazione con valori di default |
| `systemd/family-planner.service` | Unit file per il servizio systemd |
