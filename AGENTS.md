# Family Planner — Agent Instructions

Questo file definisce le istruzioni sempre attive per tutti gli agenti AI che lavorano su questo repository. Si applica a ogni interazione nel workspace.

---

## Identità del Progetto

**Family Planner** è un'applicazione Python embedded per Raspberry Pi che visualizza un calendario su display HDMI o e-ink Waveshare. Include un server web FastAPI per configurazione e anteprima browser. Il rendering è basato su **Playwright** (Chromium headless/non-headless): i template HTML Jinja2 sono la fonte unica di rendering per entrambi i display. Il design segue l'estetica tipografica del *Wall Street Journal*: niente ombre, niente bordi arrotondati, niente animazioni.

---

## Stack e Versioni

| Componente | Tecnologia |
|---|---|
| Python | 3.11+ |
| Web server | FastAPI + Uvicorn |
| Template + navigazione | Jinja2 + HTMX |
| Rendering | Playwright (Chromium) + Pillow (post-processing e-ink) |
| CalDAV | `caldav` + `icalendar` |
| Config | YAML + Pydantic v2 |
| Display HDMI | Playwright non-headless (Chromium) |
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
- Su RPi, Playwright **deve** usare il Chromium di sistema (`executable_path=/usr/bin/chromium-browser`) — non il bundle Playwright, per evitare ~300 MB di overhead su disco
- HTMX è incluso come asset locale in `base.html` — non è un pacchetto pip, non va aggiunto a `requirements.txt`
- Pillow è usato **solo** per post-processing e-ink (`EinkRenderer`) — non per rendering del calendario

---

## Architettura — Regole Invarianti

1. **Pipeline di rendering unificata**: `PlaywrightRenderer` è la fonte unica di rendering — `screenshot()` → `PIL.Image` condiviso da HDMI ed e-ink. I template HTML sono la fonte di verità del layout. Non duplicare logica di rendering in Python.
2. **EinkRenderer** è solo post-processing: riceve un `PIL.Image` già composto e applica quantizzazione palette + dithering Floyd-Steinberg.
3. **FastAPI è la fonte HTML per PlaywrightRenderer**: `GET /` produce il contenuto che Playwright renderizza per entrambi i display. `HdmiDisplay` usa Playwright non-headless; nessun subprocess Chromium separato.
4. **Riavvio graceful**: `POST /config` salva il file YAML e riavvia Uvicorn con SIGHUP — non terminare il processo bruscamente.
5. **Nessun scroll** nel layout, eccetto il pannello dettaglio appuntamento.
6. **GPIO e touchscreen usano lo stesso meccanismo**: `page.click('#btn-nav-{action}')` — i pulsanti HTML di navigazione sono sempre presenti nel DOM; `show_buttons` controlla solo la visibilità CSS.

---

## Design System — Vincoli per Template e Renderer

- **Unità CSS**: usare esclusivamente `px` — nessun `rem`, `em`, `vw`, `vh` (display fisico a risoluzione fissa)
- **Nessuna ombra**: `box-shadow`, `text-shadow` e `drop-shadow` sono vietati
- **Nessun border-radius**: `border-radius: 0` ovunque
- **Nessuna transizione o animazione**: gli aggiornamenti sono istantanei
- **Font**: Playfair Display (headings) · IBM Plex Sans (body) · IBM Plex Mono (orari)
- **Icone**: Tabler Icons SVG outline, `stroke-width: 1.5px`, sempre `currentColor`
- **Palette**: 6 valori definiti in `docs/design.md` — non introdurre nuovi colori senza aggiornare la doc

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
2. Verificare che le modifiche ai template HTML (Jinja2/CSS) siano visivamente corrette per entrambi i display — fare screenshot via `PlaywrightRenderer` sui `width`/`height` configurati
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
