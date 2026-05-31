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

La scala è fissa in pixel per garantire coerenza sul display fisico (nessun `rem` dipendente dal viewport). I valori sono calibrati per display ad alta risoluzione (Inky Impression 13.3" 1600×1200 e simili):

| Token | Dimensione | Utilizzo |
|---|---|---|
| `--text-xs`  | 18px | Etichette secondarie, note, orari |
| `--text-sm`  | 21px | Metadati appuntamento, temperatura bioraria |
| `--text-base`| 24px | Corpo testo, nomi eventi |
| `--text-md`  | 28px | Numero giorno selezionato |
| `--text-lg`  | 38px | Data nel banner meteo, intestazione calendario |
| `--text-xl`  | 50px | Titolo sezione, elemento prominente |
| `--text-2xl` | 76px | Uso eccezionale |

Line-height uniforme: `1.3`. Letter-spacing per titoli: `0.03em`.

---

## Palette Cromatica

### Modalità Giorno (default — e-ink e HDMI)

La palette è limitata a **sei valori** per garantire la fedeltà su e-ink in scala di grigi e su display a colori.

```css
/* Sfondo */
--color-bg:          #FFFFFF;   /* bianco puro — massimo contrasto su e-ink */
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
  /* Icone meteo */
  --weather-sun:   #F5A623;   /* sole / cielo sereno */
  --weather-cloud: #9CA3AF;   /* nuvola / coperto / nebbia */
  --weather-rain:  #3B82F6;   /* pioggia / rovesci / temporale */
  --weather-snow:  #93C5FD;   /* neve / grandine */```

**Su e-ink:** il renderer quantizza automaticamente verso i valori della palette fisica del display. I colori sopra sono scelti per mappare in modo deterministico.

### Palette Spectra 6 (Pimoroni Inky Impression)

Quando `eink_palette: "spectra6"` è configurato, il post-processor quantizza verso la palette a 6 colori del pannello Pimoroni Inky Impression. Il `PillowEinkRenderer` genera comunque un'immagine RGB standard; l'`EinkRenderer` la converte in modalità palette `"P"` prima dell'invio all'hardware.

| Indice | Nome | RGB | Utilizzo |
|---|---|---|---|
| 0 | Nero | `#000000` | Testo, bordi |
| 1 | Bianco | `#FFFFFF` | Sfondo |
| 2 | Rosso | `#FF0000` | Accenti, icona meteo `sun` |
| 3 | Verde | `#00FF00` | (riservato) |
| 4 | Blu | `#0000FF` | Icona meteo `cloud-rain` |
| 5 | Giallo | `#FFFF00` | (riservato) |

Il dithering Floyd-Steinberg (`eink_dither: true`) è raccomandato con questa palette per attenuare le transizioni cromatiche nelle fotografie e nelle aree sfumate.

### Palette Icone Meteo

Le icone meteo sono tintate con colori specifici per condizione (anziché `--color-ink`), definiti in `app/renderer/tokens.py` come `WEATHER_ICON_COLORS`. Applicati sia all'icona principale nel banner superiore sia alle icone della fascia bioraria.

| Token | Valore | Condizione |
|---|---|---|
| `--weather-sun` | `#F5A623` | Sole, cielo sereno |
| `--weather-cloud` | `#9CA3AF` | Nuvola, nebbia, coperto |
| `--weather-rain` | `#3B82F6` | Pioggia, rovesci, temporale |
| `--weather-snow` | `#93C5FD` | Neve, grandine |

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

Dimensione standard icone: `16px` (inline con testo) / `20px` (pulsanti) / `24px` (intestazioni viste) / `48px` (icona meteo banner).

---

## Layout Generale

L'interfaccia è costituita da un'unica **schermata Home** con due varianti di layout selezionabili tramite configurazione. Non esiste un header separato: la data è incorporata nel banner meteo.

### Layout Portrait

Quattro fasce orizzontali impilate:

```
┌──────────────────────────────────────────────────────────┐
│  BANNER METEO  (altezza fissa: 217px)                    │
│  Data · Icona meteo · Temperatura attuale · Max/Min      │
│  ──────────────────────────────────────────────────────  │
│  Previsioni biorarie: 6 celle · Icona 48px · Temp        │
├──────────────────────────────────────────────────────────┤
│  CALENDARIO MENSILE  (altezza fissa: 560px)              │
│  Vista mensile visiva — nessuna interazione              │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  LISTA APPUNTAMENTI  (altezza variabile)                 │
│  Dal prossimo appuntamento in poi — stile Agenda         │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  FOOTER  (altezza fissa: 54px)                           │
│  Indicatori di stato                                     │
└──────────────────────────────────────────────────────────┘
```

**Banner Meteo:** `border-bottom: 2px solid var(--color-rule-strong)`.  
**Calendario Mensile:** `border-bottom: 1px solid var(--color-rule-strong)`.  
**Lista Appuntamenti:** occupa l'altezza rimanente (`height − 217px − 560px − 54px`). Non scrolla.  
**Footer:** `border-top: 1px solid var(--color-rule)`. Mostra solo gli indicatori di stato a destra (nessun pulsante di navigazione).

### Layout Landscape

Due colonne affiancate + footer full-width:

```
┌───────────────────────────────┬────────────────────────────────────────┐
│  COLONNA SINISTRA  (50%)        │  COLONNA DESTRA  (50%)                 │
│                                 │                                        │
│  METEO  (217px)                 │  LISTA APPUNTAMENTI                    │
│  Data · Icona · Temperatura     │  (altezza intera content area)         │
│  Previsioni biorarie (6 celle)  │                                        │
│  ─────────────────────────────  │                                        │
│  CALENDARIO MENSILE             │                                        │
│  (altezza rimanente)            │                                        │
│                                 │                                        │
├───────────────────────────────┴────────────────────────────────────────┤
│  FOOTER  (54px, full width)                                              │
└──────────────────────────────────────────────────────────────────────────┘
```

**Separatore colonne:** `border-right: 1px solid var(--color-rule-strong)` sulla colonna sinistra, altezza `height − 54px`.  
**Sezione Meteo:** `border-bottom: 1px solid var(--color-rule)`.  
**Colonna sinistra:** larghezza `50%` (metà esatta). Esempio: 1024×600 → 512px sinistra, 512px destra; 1600×1200 → 800px sinistra, 800px destra.  
**Lista Appuntamenti:** occupa tutta l'altezza della content area (`height − 54px`).  
**Footer:** `border-top: 1px solid var(--color-rule)`. Full width, mostra solo gli indicatori di stato a destra.

Il footer è la fascia inferiore fissa (altezza `54px`). Non contiene pulsanti di navigazione. Mostra esclusivamente gli **indicatori di stato** allineati a destra, in `--text-xs`, `--color-ink-muted`:

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

- **Sotto-colonna 1 (sinistra):** icona condizione meteo Tabler `48px`, tintata con la palette colori meteo (`--weather-*`), centrata verticalmente nel banner- **Sotto-colonna 2 (centro):** temperatura attuale, `--font-body`, `40px`, `font-weight: 600`, `--color-ink`, centrata verticalmente, anchor destra
- **Sotto-colonna 3 (destra):** max e min incolonnati verticalmente, `--font-body`, `--text-xs` (18px), `--color-ink-muted`, entrambi anchor destra; `↑max` a 1/3 dell'altezza del banner, `↓min` a 2/3
- **Lato sinistro:** data, `--font-display`, `--text-lg`, formato `"Giorno, DD Mese YYYY"`, `--color-ink`
- Sfondo: `--color-bg` — nessun sfondo alternato nel banner
- Aggiornamento dati meteo: ogni ora (TTL cache provider)

**Fascia previsioni biorarie** (sotto la fascia data/meteo, altezza 127px):

```
┌────────┬────────┬────────┬────────┬────────┬────────┐
│ 14:00  │ 16:00  │ 18:00  │ 20:00  │ 22:00  │ 00:00  │
│  ⛅   │  ☁    │  🌧   │  ⛅   │  ⛅   │  ☁    │
│  18°   │  17°   │  15°   │  14°   │  13°   │  12°   │
└────────┴────────┴────────┴────────┴────────┴────────┘
```

- **6 celle** di larghezza uguale (`width / 6`): fascia corrente + 5 successive (ogni 2 ore)
- **Orario** (riga 1, in alto, centrato): `--font-mono`, `--text-xs` (18px), `--color-ink-muted`, anchor `mt` a 4px dal bordo superiore della cella
- **Icona** (riga 2, centrata verticalmente tra orario e temperatura): Tabler `48px`, tintata con la palette colori meteo (`--weather-*`), centrata orizzontalmente in cella
- **Temperatura** (riga 3, in basso, centrata): `--font-body` SemiBold, `--text-sm` (21px), `--color-ink`, baseline ancorata a 27px dal bordo inferiore della cella
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

Lista in stile Agenda, ispirata a Google Calendar. La data di ogni giorno è visualizzata in una **colonna sinistra fissa** (84px), non come separatore orizzontale. Il primo evento di ogni giornata mostra il numero del giorno e il giorno della settimana abbreviato sulla stessa riga del titolo; gli eventi successivi della stessa giornata lasciano la colonna data vuota. Ogni riga ha un **pallino colorato** all'inizio dell'area orario che indica il calendario di appartenenza. La paginazione Su/Giù sostituisce l'intera pagina — nessuno scroll CSS.

```
┌────────────────────────────────────────────────────────────────┐
│  24 DOM      ●  Tutto il giorno   Riunione team                 │
│             ●  15:00 - 16:00    Dentista                      │
│           ──────────────────────────────────────────────────  │
│             ●  17:30 - 18:30    Appuntamento                  │
│                Sala B                                          │
├────────────────────────────────────────────────────────────────┤
│  25 LUN      ●  09:00 - 10:00    Videocall con cliente          │
│             ●  12:30 - 13:30    Pranzo con Marco               │
│                Ristorante Al Porto                             │
└────────────────────────────────────────────────────────────────┘
```

> Il piccolo spazio prima del pallino (8px) è il padding sinistra dell'area orario; un padding uguale (8px) separa la fine dell'orario dall'inizio del titolo.

**Regole visive:**

- **Colonna data (84px, sinistra):**
  - **Riga singola** alla stessa altezza del titolo evento (`y = y0+30`): numero giorno (`--font-body`, `--text-md`, `--color-ink`) + giorno settimana abbreviato (`--font-body` SemiBold, `--text-xs`, `--color-ink-muted`), entrambi allineati a destra nella colonna
  - Il numero giorno è posizionato a un offset fisso dalla destra della colonna, calcolato sulla larghezza massima delle abbreviazioni (`LUN…DOM`) — garantisce l'allineamento verticale tra righe diverse
  - Formato: `"31"` + `"DOM"` (solo giorno abbreviato, nessun mese)
  - Mostrata solo per il **primo evento di ogni giornata**; le righe successive lasciano la colonna vuota
- **Colonna orario + pallino (200px):**
  - **Padding sinistro 8px** tra il bordo destro della colonna data e il centro-sinistra del pallino
  - Pallino (● 14px diametro): cerchio pieno, centrato verticalmente nella riga; colorato con `evt.color`; se non definito usa `--color-rule`
  - Orario: `--font-mono`, `--text-xs`, `--color-ink`, allineato a sinistra a destra del pallino (gap 6px), centrato verticalmente; formato `"HH:MM - HH:MM"` su riga singola
  - **Padding destro 8px** tra il bordo destro della colonna orario e il titolo dell'evento
- **Evento tutto-il-giorno:** al posto dell'orario, testo `"Tutto il giorno"` in `--font-mono`, `--text-xs`, `--color-ink`, a destra del pallino, centrato verticalmente nella riga
- **Contenuto (titolo + location):**
  - Nome evento: `--font-body`, `--text-base`, `font-weight: 600`, `--color-ink`
  - Location (se presente): `--text-xs`, `--color-ink-muted`, su riga separata sotto il nome
- **Separatore tra eventi:** `1px solid var(--color-rule-strong)` sopra la **prima riga di ogni giornata** (confine di giorno); gli eventi successivi della stessa giornata non hanno separatore — il margine superiore di 30px e la colonna data forniscono separazione visiva sufficiente, anche su display e-ink BW dove `--color-rule` (#CCCCAA, luminanza ≈ 200) scompare durante la quantizzazione
- **Lista vuota:** testo `"Nessun appuntamento"` centrato, `--color-ink-faint`, `--text-sm`

**Altezze riga (dinamiche):**

| Tipo riga | Formula | Esempio |
|---|---|---|
| Evento senza location e senza descrizione | 60 px | 60 px |
| Evento con solo location | 60 + 14 = 74 px | 74 px |
| Evento con N righe di descrizione (senza location) | 60 + N × 22 + 8 px | 1 riga → 90 px, 3 righe → 134 px |
| Evento con location e N righe di descrizione | 60 + 14 + N × 22 + 8 px | 1 riga → 104 px, 10 righe → 312 px |

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

### Modelli supportati

| `eink_model` | Driver | Risoluzione | Palette |
|---|---|---|---|
| `7in5_V2` | `waveshare_epd.epd7in5_V2` | 800×480 | `bw`, `bwr`, `4gray` |
| `7in5` | `waveshare_epd.epd7in5` | 640×384 | `bw`, `bwr` |
| `4in2` / `4in2_V2` | `waveshare_epd.epd4in2*` | 400×300 | `bw`, `bwr` |
| `5in83_V2` | `waveshare_epd.epd5in83_V2` | 648×480 | `bw`, `bwr`, `4gray` |
| `3in7` | `waveshare_epd.epd3in7` | 280×480 | `4gray` |
| `inky_impression_4` | `inky` (Pimoroni) | 600×400 | `spectra6` |
| `inky_impression_7` | `inky` (Pimoroni) | 800×480 | `spectra6` |
| `inky_impression_13` | `inky` (Pimoroni) | 1600×1200 | `spectra6` |

### Pimoroni Inky Impression (Spectra 6)

I modelli `inky_impression_*` usano la classe `InkyDisplay` (invece di `EinkDisplay`) che fa uso della libreria `inky` di Pimoroni. Il rendering pipeline è identico: `PillowEinkRenderer` → `EinkRenderer.process()` (quantizzazione `spectra6`) → `InkyDisplay.push()`.

**Fix `_busy_wait` per Inky 13.3":** la versione 2.4.0 della libreria `inky` ha un bug in `_busy_wait()` per il pannello EL133UF1 (BUSY è active-low, ma la condizione del loop è invertita). `InkyDisplay.push()` corregge il bug sostituendo `_busy_wait()` sull'istanza con un'implementazione corretta prima di chiamare `show()`.

---

## Token CSS di Riferimento

```css
:root {
  /* Tipografia */
  --font-display: 'Playfair Display', Georgia, serif;
  --font-body:    'IBM Plex Sans', Helvetica Neue, Arial, sans-serif;
  --font-mono:    'IBM Plex Mono', Courier New, monospace;

  --text-xs:   18px;
  --text-sm:   21px;
  --text-base: 24px;
  --text-md:   28px;
  --text-lg:   38px;
  --text-xl:   50px;
  --text-2xl:  76px;

  /* Colori (modalità giorno) */
  --color-bg:          #FFFFFF;
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
  --height-banner-hourly: 127px;     /* Fascia inferiore: previsioni biorarie */
  --height-banner:        217px;     /* Banner meteo totale (portrait) / sezione meteo (landscape) */
  --height-calendar: 560px;     /* Calendario mensile: 4 righe evento per cella (solo portrait) */
  --height-footer:   54px;
  --col-left-ratio:  50%;       /* Larghezza colonna sinistra in landscape */
  --border-radius:   0;         /* Mai arrotondare */
  --shadow:          none;      /* Mai ombreggiare */
}
```

---

## Display Target

Valori pixel specifici per i display supportati:

| Display | Risoluzione | Layout default | Colonna sinistra | Colonna destra | Lista appuntamenti |
|---|---|---|---|---|---|
| HDMI 7" | 1024×600 | `landscape` | 512px | 512px | 546px altezza |
| Inky Impression 13.3" | 1600×1200 | `landscape` | 800px | 800px | 1146px altezza |
| HDMI portrait (ruotato) | 600×1024 | `portrait` | — | — | 193px altezza |
| E-ink portrait (ruotato) | 1200×1600 | `portrait` | — | — | 769px altezza |

Calcoli portrait: lista = `height − 217px − 560px − 54px`.  
Calcoli landscape: lista height = `height − 54px`; colonna sinistra = `width × 0.50`.

---

## Configurazione Layout

Il layout è selezionato tramite il campo `display.layout` nel file di configurazione YAML:

```yaml
display:
  layout: "landscape"   # "landscape" | "portrait"
  eink_model: "inky_impression_13"   # vedere tabella modelli supportati
  eink_palette: "spectra6"           # "bw" | "bwr" | "4gray" | "spectra6"
  eink_dither: true                  # Floyd-Steinberg dithering
  eink_saturation: 0.5               # saturazione colori per palette spectra6 (0.0–1.0)
```

Il template HTML applica una classe CSS al tag `<body>` corrispondente:

```html
<body class="layout-landscape">
<!-- oppure -->
<body class="layout-portrait">
```

Le due classi selezionano i rispettivi blocchi CSS (flexbox colonne per landscape, stack verticale per portrait). Il `PillowEinkRenderer` legge `config.display.layout` per selezionare il metodo di rendering corrispondente.
