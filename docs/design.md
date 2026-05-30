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
| Corsivo descrizioni | **IBM Plex Sans** | Italic |
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
│  BANNER METEO  (altezza fissa: 148px)                    │
│  Data · Icona meteo · Temperatura attuale · Max/Min      │
│  ──────────────────────────────────────────────────────  │
│  Previsioni biorarie: 6 celle · Icona 24px · Temp        │
├──────────────────────────────────────────────────────────┤
│  CALENDARIO MENSILE  (altezza fissa: 462px)              │
│  Vista mensile visiva — nessuna interazione              │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  LISTA APPUNTAMENTI  (altezza variabile)                 │
│  Dal prossimo appuntamento in poi — stile Agenda         │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  FOOTER  (altezza fissa: 40px)                           │
│  Indicatori di stato                                     │
└──────────────────────────────────────────────────────────┘
```

**Banner Meteo:** `border-bottom: 2px solid var(--color-rule-strong)`.  
**Calendario Mensile:** `border-bottom: 1px solid var(--color-rule-strong)`.  
**Lista Appuntamenti:** occupa l'altezza rimanente (`height − 162px − 462px − 40px`). Non scrolla.  
**Footer:** `border-top: 1px solid var(--color-rule)`. Mostra solo gli indicatori di stato a destra (nessun pulsante di navigazione).

### Layout Landscape

Due colonne affiancate + footer full-width:

```
┌───────────────────────────────┬────────────────────────────────────────┐
│  COLONNA SINISTRA  (38%)        │  COLONNA DESTRA  (62%)                 │
│                                 │                                        │
│  METEO  (162px)                 │  LISTA APPUNTAMENTI                    │
│  Data · Icona · Temperatura     │  (altezza intera content area)         │
│  Previsioni biorarie (6 celle)  │                                        │
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
**Footer:** `border-top: 1px solid var(--color-rule)`. Full width, mostra solo gli indicatori di stato a destra.

Il footer è la fascia inferiore fissa (altezza `40px`). Non contiene pulsanti di navigazione. Mostra esclusivamente gli **indicatori di stato** allineati a destra, in `--text-xs`, `--color-ink-muted`:

| Indicatore | Contenuto |
|---|---|
| Tipo display | `e-ink` / `hdmi` — testo fisso |
| Layout | `portrait` / `landscape` — testo fisso |
| Ora corrente | `HH:MM` — aggiornato ad ogni refresh |

```
┌──────────────────────────────────────────────────────────────┐
│                                 hdmi · landscape · 09:32  │
└──────────────────────────────────────────────────────────────┘
```

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

**Fascia previsioni biorarie** (sotto la fascia data/meteo, altezza 72px):

```
┌────────┬────────┬────────┬────────┬────────┬────────┐
│ 14:00  │ 16:00  │ 18:00  │ 20:00  │ 22:00  │ 00:00  │
│  ⛅   │  ☁    │  🌧   │  ⛅   │  ⛅   │  ☁    │
│  18°   │  17°   │  15°   │  14°   │  13°   │  12°   │
│   ▼    │        │        │        │        │        │
└────────┴────────┴────────┴────────┴────────┴────────┘
```

- **6 celle** di larghezza uguale (`width / 6`): fascia corrente + 5 successive (ogni 2 ore)
- **Orario** (riga 1): `--font-mono`, `--text-xs` (11px), `--color-ink-muted`, centrato in cella
- **Icona** (riga 2): Tabler 24px, tintata `--color-ink`, centrata in cella
- **Temperatura** (riga 3): `--font-body` SemiBold, `--text-xs` (11px), `--color-ink`, centrata in cella
- **Triangolo** (▼, solo cella corrente): triangolo pieno 10×8px, `--color-ink`, ancorato al bordo basso della fascia, centrato orizzontalmente
- **Separatori verticali** tra celle: `1px solid var(--color-rule)` (non sui bordi estremi)

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
- **Oggi:** sfondo `--color-bg-alt` sull'intera cella; numero del giorno e testo eventi in `--color-ink` (nessun quadrato, nessuna inversione)
- **Festività:** numero in `--font-display`, `font-weight: bold`, `--color-holiday`
- Giorni del mese precedente/successivo: `--color-ink-faint`, nessun evento mostrato
- **Layout cella:** numero giorno nella fascia alta (18px); righe evento nella fascia inferiore
- **Righe evento:** `--font-body`, `--text-xs`, `--color-ink-muted`; formato `HH:MM Titolo` per eventi con orario, solo titolo per tutto-il-giorno; testo troncato con `…` se non entra in larghezza
- **Overflow:** se gli eventi non entrano tutti, l'ultima riga mostra `+N` in `--color-ink-faint`
- **Ordinamento per cella:** tutto-il-giorno prima, poi per orario di inizio

#### Sezione Lista Appuntamenti

Lista in stile Agenda, ispirata a Google Calendar. La data di ogni giorno è visualizzata in una **colonna sinistra fissa** (52px), non come separatore orizzontale. Il primo evento di ogni giornata mostra il numero del giorno e l'abbreviazione mese+giorno; gli eventi successivi della stessa giornata lasciano la colonna data vuota. Ogni riga ha un **bordo colorato verticale sul lato destro** che indica il calendario di appartenenza. La paginazione Su/Giù sostituisce l'intera pagina — nessuno scroll CSS.

```
┌────────────────────────────────────────────────────────────────┐
│  24  │  15:00  │  Riunione team                             ▌  │
│  MAG,DOM  │  16:00  │  Sala B                                  │
│      │  ────────────────────────────────────────────────────  │
│      │  17:30  │  Dentista                                  ▌  │
│      │  18:30  │                                               │
├────────────────────────────────────────────────────────────────┤
│  25  │  09:00  │  Videocall con cliente                     ▌  │
│  MAG,LUN  │  10:00  │                                          │
│      │  ────────────────────────────────────────────────────  │
│  12  │  12:30  │  Pranzo con Marco                          ▌  │
│      │  13:30  │  Ristorante Al Porto                          │
└────────────────────────────────────────────────────────────────┘
```

**Regole visive:**

- **Colonna data (52px, sinistra):**
  - Numero giorno: `--font-body`, `--text-md` (18px), `--color-ink`, allineato a destra nella colonna
  - Abbreviazione mese+giorno: `--font-body` SemiBold, `--text-xs` (11px), `--color-ink-muted`, formato `"MAG, DOM"`, su riga separata sotto il numero
  - Mostrata solo per il **primo evento di ogni giornata**; le righe successive lasciano la colonna vuota
  - I due elementi sono centrati verticalmente nella riga come blocco unitario
- **Colonna orario (56px):**
  - Orario inizio: `--font-mono`, `--text-sm`, `--color-ink-muted`, allineato a destra, posizionato sopra la mezzeria verticale della riga
  - Orario fine: `--font-mono`, `--text-sm`, `--color-ink-faint`, allineato a destra, posizionato sotto la mezzeria verticale della riga
  - `border-right: 1px solid var(--color-rule)` separa la colonna orario dal contenuto
- **Evento tutto-il-giorno:** al posto dell'orario, testo `"Tutto il giorno"` in `--color-ink-faint`, centrato verticalmente nella riga
- **Contenuto (titolo + location):**
  - Nome evento: `--font-body`, `--text-base`, `font-weight: 600`, `--color-ink`
  - Location (se presente): `--text-xs`, `--color-ink-muted`, su riga separata sotto il nome
- **Separatore tra eventi:** `1px solid var(--color-rule)` sopra ogni riga che NON è la prima della giornata; la prima riga di ogni giornata non ha separatore sopra (la colonna data funge da separatore visivo)
- **Bordo colorato a destra (3px):** rettangolo verticale all'estremo destro di ogni riga, colorato con il colore del calendario sorgente (`evt.color`); se il colore non è definito, usa `--color-rule`
- **Lista vuota:** testo `"Nessun appuntamento"` centrato, `--color-ink-faint`, `--text-sm`

**Altezze riga (dinamiche):**

| Tipo riga | Formula | Esempio |
|---|---|---|
| Evento senza location e senza descrizione | 40 px | 40 px |
| Evento con solo location | 40 + 14 = 54 px | 54 px |
| Evento con N righe di descrizione (senza location) | 40 + N × 15 + 8 px | 1 riga → 63 px, 3 righe → 93 px |
| Evento con location e N righe di descrizione | 40 + 14 + N × 15 + 8 px | 1 riga → 77 px, 10 righe → 212 px |

I 8 px finali (solo quando è presente una descrizione) aggiungono un respiro visivo inferiore equivalente allo spazio bianco sopra il glifo del titolo.

**Formattazione descrizione (rich text HTML):**

La descrizione può contenere HTML proveniente da sorgenti CalDAV. Il renderer interpreta i seguenti tag:

| Tag HTML | Effetto visivo |
|---|---|
| `<b>`, `<strong>` | Testo in IBM Plex Sans SemiBold |
| `<i>`, `<em>` | Testo in IBM Plex Sans Italic |
| `<u>` | Testo con riga orizzontale sottostante (1 px, `--color-ink-faint`) |
| `<a href="...">` | Testo in `--color-ink-muted` + sottolineatura |
| `<br>`, `</p>`, `</div>`, `</li>` | A-capo |
| `<ul><li>` | Riga con prefisso `• ` |
| `<ol><li>` | Riga con prefisso `N. ` (contatore progressivo) |

Tag non riconosciuti vengono eliminati silenziosamente. Il testo plain (senza tag) viene diviso su `\n`. Ogni riga è troncata con `…` se supera la larghezza disponibile.

---

## Flusso di Navigazione

L'interfaccia ha un'unica schermata. Non esiste navigazione — viene sempre mostrato il giorno corrente.

---

## Indicatori di Stato (Footer)

Gli indicatori di stato sono incorporati nella parte destra del footer, in `--text-xs`, `--color-ink-muted`:

| Indicatore | Contenuto |
|---|---|
| Tipo display | `e-ink` / `hdmi` — testo fisso |
| Layout | `portrait` / `landscape` — testo fisso |
| Ora corrente | `HH:MM` — aggiornato ad ogni refresh |

---

## Comportamento E-Ink Specifico

Quando `display.type = "eink"`:

1. **Palette:** il renderer usa solo i valori quantizzati della palette del modello configurato. I colori sopra sono scelti per mappare in modo deterministico.
2. **Footer non interattivo:** il footer mostra la legenda testuale identica a quella HDMI, ma i tasti non sono cliccabili. I pulsanti fisici sono l'unico mezzo di interazione.
3. **Dithering:** il post-processor applica Floyd-Steinberg alle aree di testo piccolo per migliorare la leggibilità su display a bassa risoluzione.
4. **Refresh parziale:** nel layout landscape, il calendario mensile (colonna sinistra, sezione inferiore) è l'area più statica e ideale per partial refresh separato. La lista appuntamenti (colonna destra / area inferiore portrait) cambia ad ogni navigazione.

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
  --height-banner-main:   90px;      /* Fascia superiore: data e meteo corrente */
  --height-banner-hourly: 58px;      /* Fascia inferiore: previsioni biorarie */
  --height-banner:        148px;     /* Banner meteo totale (portrait) / sezione meteo (landscape) */
  --height-calendar: 462px;     /* Calendario mensile: 4 righe evento per cella (solo portrait) */
  --height-footer:   40px;
  --col-left-ratio:  38%;       /* Larghezza colonna sinistra in landscape */
  --border-radius:   0;         /* Mai arrotondare */
  --shadow:          none;      /* Mai ombreggiare */
}
```

---

## Display Target

Valori pixel specifici per i display supportati:

| Display | Risoluzione | Layout default | Colonna sinistra | Colonna destra | Lista appuntamenti |
|---|---|---|---|---|---|
| HDMI 7" | 1024×600 | `landscape` | 389px | 634px | 560px altezza |
| Inky Impression 13.3" | 1600×1200 | `landscape` | 608px | 991px | 1160px altezza |
| HDMI portrait (ruotato) | 600×1024 | `portrait` | — | — | 374px altezza |
| E-ink portrait (ruotato) | 1200×1600 | `portrait` | — | — | 950px altezza |

Calcoli portrait: lista = `height − 148px − 462px − 40px`.  
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
