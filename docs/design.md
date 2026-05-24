# Design — Family Planner Calendar

## Filosofia di Design

Il calendario è concepito come una **pagina stampata interattiva**, non come un'applicazione digitale classica. Il riferimento estetico è il quotidiano finanziario *The Wall Street Journal*: tipografia rigorosa, gerarchia visiva costruita esclusivamente attraverso peso del carattere, dimensione e spazio bianco. Nessun elemento decorativo superfluo.

**Principi fondamentali:**

- Assenza totale di ombreggiature (`box-shadow`, `text-shadow`, `drop-shadow`)
- Assenza di bordi arrotondati (`border-radius: 0` ovunque)
- Nessuna animazione o transizione — gli aggiornamenti sono istantanei
- Il layout non scrolla mai
- La griglia è l'unico strumento di composizione

---

## Tipografia

### Font Stack

| Ruolo | Famiglia | Stile |
|---|---|---|
| Titoli e intestazioni | **Playfair Display** | Regular / Bold |
| Corpo e dati | **IBM Plex Sans** | Regular / Medium / SemiBold |
| Monospazio (orari) | **IBM Plex Mono** | Regular |

Tutte le famiglie appartengono al Google Fonts catalog, a rendering ottimizzato per schermo, incluso e-ink. Il fallback universale è `serif` per i titoli e `sans-serif` per il corpo.

```css
--font-display: 'Playfair Display', Georgia, serif;
--font-body:    'IBM Plex Sans', Helvetica Neue, Arial, sans-serif;
--font-mono:    'IBM Plex Mono', Courier New, monospace;
```

### Scala Tipografica

La scala è fissa in pixel per garantire coerenza sul display fisico (nessun `rem` dipendente dal viewport):

| Token | Dimensione | Utilizzo |
|---|---|---|
| `--text-xs`  | 11px | Etichette secondarie, note |
| `--text-sm`  | 13px | Orari, metadati appuntamento |
| `--text-base`| 15px | Corpo testo, nomi eventi |
| `--text-md`  | 18px | Numero giorno selezionato |
| `--text-lg`  | 24px | Data nel banner meteo, intestazione calendario |
| `--text-xl`  | 32px | Titolo sezione, elemento prominente |
| `--text-2xl` | 48px | Uso eccezionale |

Line-height uniforme: `1.3`. Letter-spacing per titoli: `0.03em`.

---

## Palette Cromatica

### Modalità Giorno (default — e-ink e HDMI)

La palette è limitata a **sei valori** per garantire la fedeltà su e-ink in scala di grigi e su display a colori.

```css
/* Sfondo */
--color-bg:          #F8F6F0;   /* bianco avorio — carta giornale */
--color-bg-alt:      #EEECE6;   /* grigio chiarissimo — righe alternate, fasce */

/* Testo */
--color-ink:         #111111;   /* nero quasi-assoluto */
--color-ink-muted:   #666666;   /* grigio medio — metadati, orari passati */
--color-ink-faint:   #AAAAAA;   /* grigio chiaro — separatori, placeholder */

/* Accenti */
--color-accent:      #1A1A1A;   /* quasi-nero — selezione, oggi */
--color-holiday:     #444444;   /* grigio scuro — evidenziazione festività */

/* Bordi */
--color-rule:        #CCCCAA;   /* linea color seppia — divisori orizzontali */
--color-rule-strong: #333333;   /* linea scura — bordo elemento selezionato */
```

**Su e-ink:** il renderer quantizza automaticamente verso i valori della palette fisica del display. I colori sopra sono progettati per collassare in modo prevedibile su palette BW, BWR e 4-gray.

### Modalità Notte (solo display HDMI / tradizionale)

La modalità notte si attiva **esclusivamente** quando `display.type = "hdmi"` nella configurazione. Su e-ink rimane sempre la modalità giorno.

```css
/* Sfondo */
--color-bg:          #0D0D0D;
--color-bg-alt:      #1A1A1A;

/* Testo */
--color-ink:         #E8E6E0;
--color-ink-muted:   #888888;
--color-ink-faint:   #444444;

/* Accenti */
--color-accent:      #E8E6E0;
--color-holiday:     #AAAAAA;

/* Bordi */
--color-rule:        #2A2A2A;
--color-rule-strong: #CCCCAA;
```

---

## Iconografia — Tabler Icons

Il set di icone adottato è **Tabler Icons** (versione SVG outline, stroke-width `1.5px`). Le icone sono sempre monocromatiche, colorizzate tramite `currentColor`.

| Icona Tabler | Utilizzo |
|---|---|
| `icon-sun` | Condizione soleggiato — banner meteo / indicatore modalità giorno |
| `icon-cloud` | Condizione nuvoloso — banner meteo |
| `icon-cloud-rain` | Condizione piovoso — banner meteo |
| `icon-snowflake` | Condizione neve — banner meteo |
| `icon-chevron-up` | Pulsante Su (footer) |
| `icon-chevron-down` | Pulsante Giù (footer) |
| `icon-corner-up-left` | Pulsante Oggi / Ritorna (footer) |
| `icon-check` | Pulsante Invio — disabilitato (footer) |
| `icon-moon` | Indicatore modalità notte (footer) |
| `icon-clock` | Orario appuntamento — lista |
| `icon-map-pin` | Luogo appuntamento — lista |
| `icon-star` | Festività / Giorno speciale — calendario mensile |

Dimensione standard icone: `16px` (inline con testo) / `20px` (pulsanti) / `24px` (intestazioni viste) / `40px` (icona meteo banner).

---

## Layout Generale

L'interfaccia è costituita da un'unica **schermata Home** con due varianti di layout selezionabili tramite configurazione. Non esiste un header separato: la data è incorporata nel banner meteo.

### Layout Portrait

Quattro fasce orizzontali impilate:

```
┌──────────────────────────────────────────────────────────┐
│  BANNER METEO  (altezza fissa: 90px)                     │
│  Data · Icona meteo · Temperatura attuale · Max/Min      │
├──────────────────────────────────────────────────────────┤
│  CALENDARIO MENSILE  (altezza fissa: 250px)              │
│  Vista mensile visiva — nessuna interazione              │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  LISTA APPUNTAMENTI  (altezza variabile)                 │
│  Dal prossimo appuntamento in poi — stile Agenda         │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  FOOTER  (altezza fissa: 40px)                           │
│  Pulsanti navigazione · Indicatori di stato              │
└──────────────────────────────────────────────────────────┘
```

**Banner Meteo:** `border-bottom: 2px solid var(--color-rule-strong)`.  
**Calendario Mensile:** `border-bottom: 1px solid var(--color-rule-strong)`.  
**Lista Appuntamenti:** occupa l'altezza rimanente (`height − 90px − 250px − 40px`). Non scrolla — Su/Giù sostituisce l'intera pagina.  
**Footer:** `border-top: 1px solid var(--color-rule)`.

### Layout Landscape

Due colonne affiancate + footer full-width:

```
┌───────────────────────────────┬────────────────────────────────────────┐
│  COLONNA SINISTRA  (38%)        │  COLONNA DESTRA  (62%)                 │
│                                 │                                        │
│  METEO  (90px)                  │  LISTA APPUNTAMENTI                    │
│  Data · Icona · Temperatura     │  (altezza intera content area)         │
│  ─────────────────────────────  │                                        │
│  CALENDARIO MENSILE             │                                        │
│  (altezza rimanente)            │                                        │
│                                 │                                        │
├───────────────────────────────┴────────────────────────────────────────┤
│  FOOTER  (40px, full width)                                              │
└──────────────────────────────────────────────────────────────────────────┘
```

**Separatore colonne:** `border-right: 1px solid var(--color-rule-strong)` sulla colonna sinistra, altezza `height − 40px`.  
**Sezione Meteo:** `border-bottom: 1px solid var(--color-rule)`.  
**Colonna sinistra:** larghezza `38%` (≈ rapporto aureo editoriale). Esempio: 1024×600 → 389px sinistra, 634px destra.  
**Lista Appuntamenti:** occupa tutta l'altezza della content area (`height − 40px`).  
**Footer:** `border-top: 1px solid var(--color-rule)`.

---

## Pulsanti di Interazione

### Pulsanti Fisici

La mappatura dei 4 pulsanti fisici (o delle 4 azioni da tastiera):

| Pulsante | Tasto tastiera | Azione |
|---|---|---|
| Oggi / Ritorna | `Escape` | Reimposta la lista alla data odierna |
| Su | `ArrowUp` | Pagina precedente nella lista appuntamenti |
| Giù | `ArrowDown` | Pagina successiva nella lista appuntamenti |
| Invio | `Enter` | Disabilitato — nessuna azione |

### Footer Interattivo (pulsanti virtuali)

Non esiste alcun overlay flottante. Il footer è l'**unico** elemento interattivo: su `display.type = "hdmi"` (o modalità browser) ogni tasto nella legenda diventa un'area cliccabile con mouse o touch. La legenda è già presente su tutti i display — su e-ink funge da sola guida testuale, su HDMI è anche interfaccia touch/click.

```
┌──────────────────────────────────────────────────────────────┐
│  [ ↑ Su ]  [ ↓ Giù ]  [ ↵ — ]  [ ← Oggi ]                  │
└──────────────────────────────────────────────────────────────┘
```

**Specifica footer interattivo:**
- I quattro tasti occupano la fascia footer come elementi `inline-block` separati da `border-right: 1px solid var(--color-rule)`
- Ogni tasto: altezza `40px` (= altezza footer), padding orizzontale `16px`, icona Tabler `16px` + etichetta testuale in `--text-xs`
- Allineamento: i tasti sono raggruppati a sinistra; gli indicatori di stato (display, layout, ora) restano a destra
- Su HDMI: `cursor: pointer`; area hit minima `44px` di larghezza per accessibilità touch
- Il tasto "Invio" è sempre disabilitato visivamente (`--color-ink-faint`, `pointer-events: none`)
- Su e-ink: il footer è identico ma non interattivo — i pulsanti fisici rimangono l'unico mezzo di input

---

## Schermate

---

### Home (schermata unica)

**Scopo:** mostra la situazione meteorologica, il calendario mensile corrente e la lista degli appuntamenti dal prossimo in poi, in un unico colpo d'occhio.  
**Navigazione:** Su/Giù pagina la lista appuntamenti; Esc reimposta alla data odierna; Enter disabilitato.

#### Sezione Meteo

Banner superiore in portrait, sezione superiore della colonna sinistra in landscape.

```
┌──────────────────────────────────────────────────────────────┐
│  Domenica, 24 Maggio 2026         ⛅   18°  ↑22°            │
│                                            ↓14°            │
└──────────────────────────────────────────────────────────────┘
```

Il lato destro è un blocco a tre sotto-colonne allineato al margine destro:

- **Sotto-colonna 1 (sinistra):** icona condizione meteo Tabler `40px`, `currentColor`, centrata verticalmente nel banner
- **Sotto-colonna 2 (centro):** temperatura attuale, `--font-body`, `40px`, `font-weight: 600`, `--color-ink`, centrata verticalmente, anchor destra
- **Sotto-colonna 3 (destra):** max e min incolonnati verticalmente, `--font-body`, `--text-xs` (11px), `--color-ink-muted`, entrambi anchor destra; `↑max` a 1/3 dell'altezza del banner, `↓min` a 2/3
- **Lato sinistro:** data, `--font-display`, `--text-lg`, formato `"Giorno, DD Mese YYYY"`, `--color-ink`
- Sfondo: `--color-bg` — nessun sfondo alternato nel banner
- Aggiornamento dati meteo: ogni ora (TTL cache provider)

#### Sezione Calendario Mensile

Il calendario mensile è **puramente visivo** — non risponde a nessuna interazione dell'utente.

```
┌──────────────────────────────────────────────────────────────┐
│                       MAGGIO 2026                            │
│  LUN   MAR   MER   GIO   VEN   SAB   DOM                    │
│   27    28    29    30     1     2     3                     │
│    4     5     6     7     8     9    10                     │
│   11    12    13    14    15    16    17                     │
│   18    19    20    21    22    23   [24]                    │
│   25    26    27    28    29    30    31                     │
└──────────────────────────────────────────────────────────────┘
```

**Regole visive:**

- Intestazione mese: `--font-body`, `--text-sm`, uppercase, `letter-spacing: 0.08em`, centrata
- Intestazione colonne (L M M G V S D): `--text-xs`, `--color-ink-muted`
- Numeri giorni: `--text-xs`, `--font-body`, `--color-ink`
- **Oggi:** sfondo `--color-accent`, testo `--color-bg`, quadrato `16×16px` netto
- **Festività:** numero in `--font-display`, `font-weight: bold`, `--color-holiday`
- Giorni del mese precedente/successivo: `--color-ink-faint`
- Nessun indicatore di eventi nel calendario

#### Sezione Lista Appuntamenti

Lista in stile Agenda, ordinata cronologicamente. Gli eventi sono raggruppati per giorno con separatori di data. La paginazione Su/Giù sostituisce l'intera pagina — nessuno scroll CSS.

```
┌──────────────────────────────────────────────────────────────┐
│  ── OGGI, DOMENICA 24 MAGGIO ──────────────────────────────  │
│  15:00  │  Riunione team                                     │
│         │  Sala B                                            │
│  ─────────────────────────────────────────────────────────   │
│  17:30  │  Dentista                                          │
│  ─────────────────────────────────────────────────────────   │
│                                                              │
│  ── LUNEDÌ 25 MAGGIO ──────────────────────────────────────  │
│  09:00  │  Videocall con cliente                             │
│  ─────────────────────────────────────────────────────────   │
│  12:30  │  Pranzo con Marco                                  │
│         │  Ristorante Al Porto                               │
└──────────────────────────────────────────────────────────────┘
```

**Regole visive:**

- **Separatori di data:** testo uppercase, `--text-xs`, `--font-body`, `--color-ink-muted`; la data odierna mostra `"OGGI, GIORNO DD MESE"`, le successive solo `"GIORNO DD MESE"`; linee orizzontali `--color-rule` ai lati del testo
- **Riga appuntamento:**
  - Orario: `--font-mono`, `--text-sm`, `--color-ink-muted`, larghezza fissa `56px`, allineato a destra, `border-right: 1px solid var(--color-rule)`
  - Nome evento: `--font-body`, `--text-base`, `font-weight: 600`, `--color-ink`
  - Location (se presente): `--text-xs`, `--color-ink-muted`, su riga separata sotto il nome
  - Separatore tra eventi: `border-bottom: 1px solid var(--color-rule)`
- **Evento tutto-il-giorno:** al posto dell'orario, testo `"Tutto il giorno"` in `--color-ink-faint`
- **Lista vuota:** testo `"Nessun appuntamento"` centrato, `--color-ink-faint`, `--text-sm`

---

## Flusso di Navigazione

L'interfaccia ha un'unica schermata. Non esiste navigazione gerarchica.

```
HOME
  ↑ Esc   → ancora_data = oggi  (reimposta alla data corrente)
  ↑ Su    → ancora_data -= N   (pagina precedente)
  ↓ Giù   → ancora_data += N   (pagina successiva)
  ↵ Enter → nessuna azione
```

L'`ancora_data` determina il primo giorno mostrato nella lista appuntamenti.

---

## Indicatori di Stato (Footer)

L'header separato è eliminato. Gli indicatori di stato sono incorporati nella parte destra del footer, in `--text-xs`, `--color-ink-muted`:

| Indicatore | Contenuto |
|---|---|
| Tipo display | `e-ink` / `hdmi` — testo fisso |
| Layout | `portrait` / `landscape` — testo fisso |
| Modalità colore | `☀ Giorno` / `☾ Notte` — solo hdmi |
| Ora corrente | `HH:MM` — aggiornato ad ogni refresh |

---

## Comportamento E-Ink Specifico

Quando `display.type = "eink"`:

1. **Palette:** il renderer usa solo i valori quantizzati della palette del modello configurato. I colori sopra sono scelti per mappare in modo deterministico.
2. **Nessuna modalità notte:** l'interfaccia è sempre in modalità giorno. Il toggle notte è nascosto.
3. **Footer non interattivo:** il footer mostra la legenda testuale identica a quella HDMI, ma i tasti non sono cliccabili. I pulsanti fisici sono l'unico mezzo di interazione.
4. **Dithering:** il post-processor applica Floyd-Steinberg alle aree di testo piccolo per migliorare la leggibilità su display a bassa risoluzione.
5. **Refresh parziale:** nel layout landscape, il calendario mensile (colonna sinistra, sezione inferiore) è l'area più statica e ideale per partial refresh separato. La lista appuntamenti (colonna destra / area inferiore portrait) cambia ad ogni navigazione.

---

## Token CSS di Riferimento

```css
:root {
  /* Tipografia */
  --font-display: 'Playfair Display', Georgia, serif;
  --font-body:    'IBM Plex Sans', Helvetica Neue, Arial, sans-serif;
  --font-mono:    'IBM Plex Mono', Courier New, monospace;

  --text-xs:   11px;
  --text-sm:   13px;
  --text-base: 15px;
  --text-md:   18px;
  --text-lg:   24px;
  --text-xl:   32px;
  --text-2xl:  48px;

  /* Colori (modalità giorno) */
  --color-bg:          #F8F6F0;
  --color-bg-alt:      #EEECE6;
  --color-ink:         #111111;
  --color-ink-muted:   #666666;
  --color-ink-faint:   #AAAAAA;
  --color-accent:      #1A1A1A;
  --color-holiday:     #444444;
  --color-rule:        #CCCCAA;
  --color-rule-strong: #333333;

  /* Struttura */
  --height-banner:   90px;      /* Banner meteo (portrait) / sezione meteo (landscape) */
  --height-calendar: 250px;     /* Calendario mensile in portrait */
  --height-footer:   40px;
  --col-left-ratio:  38%;       /* Larghezza colonna sinistra in landscape */
  --border-radius:   0;         /* Mai arrotondare */
  --shadow:          none;      /* Mai ombreggiare */
}

[data-theme="night"] {
  --color-bg:          #0D0D0D;
  --color-bg-alt:      #1A1A1A;
  --color-ink:         #E8E6E0;
  --color-ink-muted:   #888888;
  --color-ink-faint:   #444444;
  --color-accent:      #E8E6E0;
  --color-holiday:     #AAAAAA;
  --color-rule:        #2A2A2A;
  --color-rule-strong: #CCCCAA;
}
```

---

## Display Target

Valori pixel specifici per i display supportati:

| Display | Risoluzione | Layout default | Colonna sinistra | Colonna destra | Lista appuntamenti |
|---|---|---|---|---|---|
| HDMI 7" | 1024×600 | `landscape` | 389px | 634px | 560px altezza |
| Inky Impression 13.3" | 1600×1200 | `landscape` | 608px | 991px | 1160px altezza |
| HDMI portrait (ruotato) | 600×1024 | `portrait` | — | — | 644px altezza |
| E-ink portrait (ruotato) | 1200×1600 | `portrait` | — | — | 1220px altezza |

Calcoli portrait: lista = `height − 90px − 250px − 40px`.  
Calcoli landscape: lista height = `height − 40px`; colonna sinistra = `width × 0.38`.

---

## Configurazione Layout

Il layout è selezionato tramite il campo `display.layout` nel file di configurazione YAML:

```yaml
display:
  layout: "landscape"   # "landscape" | "portrait"
```

Il template HTML applica una classe CSS al tag `<body>` corrispondente:

```html
<body class="layout-landscape">
<!-- oppure -->
<body class="layout-portrait">
```

Le due classi selezionano i rispettivi blocchi CSS (flexbox colonne per landscape, stack verticale per portrait). Il `PillowEinkRenderer` legge `config.display.layout` per selezionare il metodo di rendering corrispondente.
