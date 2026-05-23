# Family Planner — Agent Instructions

Questo file definisce le istruzioni sempre attive per tutti gli agenti AI che lavorano su questo repository. Si applica a ogni interazione nel workspace.

---

## Identità del Progetto

**Family Planner** è un'applicazione Python embedded per Raspberry Pi che visualizza un calendario su display HDMI (pygame/SDL2) o e-ink Waveshare. Include un server web FastAPI per configurazione e anteprima browser. Il design segue l'estetica tipografica del *Wall Street Journal*: niente ombre, niente bordi arrotondati, niente animazioni.

---

## Stack e Versioni

| Componente | Tecnologia |
|---|---|
| Python | 3.11+ |
| Web server | FastAPI + Uvicorn |
| Template | Jinja2 |
| Rendering | Pillow (PIL) |
| CalDAV | `caldav` + `icalendar` |
| Config | YAML + Pydantic v2 |
| Display HDMI | pygame (SDL2) |
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
- Nessuna dipendenza da browser, Chromium, X11 o Wayland per il display HDMI — pygame possiede l'intera finestra

---

## Architettura — Regole Invarianti

1. **Pipeline di rendering unificata**: `ImageRenderer` (Pillow) è condiviso da HDMI ed e-ink. Non duplicare logica di rendering per i due display.
2. **EinkRenderer** è solo post-processing: riceve un `PIL.Image` già composto e applica quantizzazione palette + dithering Floyd-Steinberg.
3. **FastAPI non drive il display HDMI**: `HdmiDisplay` legge direttamente dall'`ImageRenderer` via loop interno pygame, senza passare per HTTP.
4. **Riavvio graceful**: `POST /config` salva il file YAML e riavvia Uvicorn con SIGHUP — non terminare il processo bruscamente.
5. **Nessun scroll** nel layout, eccetto il pannello dettaglio appuntamento.

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
2. Verificare che le modifiche a `ImageRenderer` siano compatibili con entrambi i display
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
