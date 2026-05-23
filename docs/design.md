# Design — Family Planner Calendar

## Filosofia di Design

Il calendario è concepito come una **pagina stampata interattiva**, non come un'applicazione digitale classica. Il riferimento estetico è il quotidiano finanziario *The Wall Street Journal*: tipografia rigorosa, gerarchia visiva costruita esclusivamente attraverso peso del carattere, dimensione e spazio bianco. Nessun elemento decorativo superfluo.

**Principi fondamentali:**

- Assenza totale di ombreggiature (`box-shadow`, `text-shadow`, `drop-shadow`)
- Assenza di bordi arrotondati (`border-radius: 0` ovunque)
- Nessuna animazione o transizione — gli aggiornamenti sono istantanei
- Il layout non scrolla mai, ad eccezione del dettaglio appuntamento
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
| `--text-lg`  | 24px | Intestazione settimana / mese corrente |
| `--text-xl`  | 32px | Titolo mese nella vista mensile |
| `--text-2xl` | 48px | Anno nella vista annuale |

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
| `icon-calendar-month` | Vista mensile — intestazione |
| `icon-calendar-week` | Vista settimanale — intestazione |
| `icon-calendar-day` | Vista giornaliera — intestazione |
| `icon-calendar-event` | Dettaglio appuntamento — intestazione |
| `icon-chevron-up` | Pulsante Su (overlay virtuale) |
| `icon-chevron-down` | Pulsante Giù (overlay virtuale) |
| `icon-corner-up-left` | Pulsante Esci / Ritorna (overlay virtuale) |
| `icon-check` | Pulsante Invio (overlay virtuale) |
| `icon-sun` | Indicatore modalità giorno |
| `icon-moon` | Indicatore modalità notte |
| `icon-clock` | Orario appuntamento |
| `icon-map-pin` | Luogo appuntamento |
| `icon-users` | Partecipanti |
| `icon-repeat` | Evento ricorrente |
| `icon-star` | Festività / Giorno speciale |

Dimensione standard icone: `16px` (inline con testo) / `20px` (pulsanti) / `24px` (intestazioni viste).

---

## Layout Generale

Ogni schermata è divisa in **tre fasce orizzontali fisse**:

```
┌─────────────────────────────────────────────────────────┐
│  HEADER  (altezza fissa: 56px)                          │
│  Vista corrente · Navigazione testuale · Data           │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  CONTENT AREA  (altezza variabile — occupa lo spazio     │
│  rimanente)                                             │
│                                                          │
├─────────────────────────────────────────────────────────┤
│  FOOTER  (altezza fissa: 40px)                          │
│  Stato · Legenda scorciatoie tasti fisici               │
└─────────────────────────────────────────────────────────┘
```

**Header:** separato dal contenuto da una `border-bottom: 2px solid var(--color-rule-strong)`.  
**Footer:** separato dal contenuto da una `border-top: 1px solid var(--color-rule)`. Su HDMI i quattro tasti della legenda sono cliccabili (v. *Footer Interattivo*).  
**Content area:** non scrolla mai (eccetto dettaglio appuntamento).

---

## Pulsanti di Interazione

### Pulsanti Fisici

La mappatura dei 4 pulsanti fisici (o delle 4 azioni da tastiera):

| Pulsante | Tasto tastiera | Azione |
|---|---|---|
| Esci / Ritorna | `Escape` | Torna alla schermata precedente |
| Su | `ArrowUp` | Sposta la selezione verso l'alto / indietro |
| Giù | `ArrowDown` | Sposta la selezione verso il basso / avanti |
| Invio | `Enter` | Conferma la selezione / entra nella schermata |

### Footer Interattivo (pulsanti virtuali)

Non esiste alcun overlay flottante. Il footer è l'**unico** elemento interattivo: su `display.type = "hdmi"` (o modalità browser) ogni tasto nella legenda diventa un'area cliccabile con mouse o touch. La legenda è già presente su tutti i display — su e-ink funge da sola guida testuale, su HDMI è anche interfaccia touch/click.

```
┌──────────────────────────────────────────────────────────────┐
│  [ ↑ Su ]  [ ↓ Giù ]  [ ↵ Invio ]  [ ← Esci ]              │
└──────────────────────────────────────────────────────────────┘
```

**Specifica footer interattivo:**
- I quattro tasti occupano la fascia footer come elementi `inline-block` separati da `border-right: 1px solid var(--color-rule)`
- Ogni tasto: altezza `40px` (= altezza footer), padding orizzontale `16px`, icona Tabler `16px` + etichetta testuale in `--text-xs`
- Allineamento: i tasti sono raggruppati a sinistra; eventuali indicatori di stato (display, ora) restano a destra
- Su HDMI: `cursor: pointer`; area hit minima `44px` di larghezza per accessibilità touch
- Il tasto "Esci" è disabilitato visivamente (`--color-ink-faint`, `pointer-events: none`) sulla vista annuale
- Su e-ink: il footer è identico ma non interattivo — i pulsanti fisici rimangono l'unico mezzo di input

---

## Schermate

---

### 1. Vista Annuale

**Scopo:** orientamento rapido nell'anno. Permette di selezionare un mese.  
**Navigazione:** Su/Giù seleziona il mese precedente/successivo; Invio entra nella vista mensile. Nessun tasto "Esci" attivo.

#### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ANNO: 2026                                    [icona-sole]  │  ← Header
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   GEN          FEB          MAR          APR                 │
│   ──────────   ──────────   ──────────   ──────────          │
│   L M M G V S D  L M ...   L M ...      L M ...             │
│   ·  ·  ·  1  2  3  4                                       │
│   5  6  7  8  9 10 11                                        │
│   ...                                                        │
│                                                              │
│   MAG ◄══ SELEZIONATO     GIU          LUG          AGO     │
│   ══════════════════════                                     │
│   ...                                                        │
│                                                              │
│   SET          OTT          NOV          DIC                 │
│   ...                                                        │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  ↑↓ Seleziona mese · ↵ Apri mese                            │  ← Footer
└──────────────────────────────────────────────────────────────┘
```

#### Regole visive

- **Griglia 4×3:** i 12 mesi sono disposti in 3 righe da 4 colonne, a occupare tutta la content area.
- Ogni mini-calendario mostra solo i **numeri dei giorni** in `--text-xs`. Nessuna etichetta di evento.
- Intestazione mese: `--font-body`, `--text-sm`, uppercase, `letter-spacing: 0.08em`.
- **Festività:** il numero del giorno è in `--font-display`, `font-weight: bold`, `--color-holiday`. Un punto `·` sottostante indica la presenza di una festività nazionale.
- **Mese selezionato:** il mini-calendario riceve `outline: 2px solid var(--color-rule-strong)` sul bordo esterno, nessun riempimento di sfondo.
- Il giorno corrente (se il mese visualizzato è il mese corrente): sfondo `--color-accent`, testo `--color-bg` (inversione) — un quadrato netto `16×16px`.

---

### 2. Vista Mensile

**Scopo:** panoramica del mese selezionato. Permette di selezionare una settimana.  
**Navigazione:** Su/Giù seleziona la settimana precedente/successiva; Invio entra nella vista settimanale. Esci torna alla vista annuale.

#### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ← Esci   MAGGIO 2026                        [icona-mese]   │  ← Header
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   LUN   MAR   MER   GIO   VEN   SAB   DOM                   │
│   ─────────────────────────────────────────────────────      │
│                                                              │
│   27    28    29    30     1     2     3                     │
│   ──────────────────────────────────────────────────         │
│    4     5     6     7     8     9    10                     │
│   ══════ SETTIMANA SELEZIONATA ═══════════════               │
│   11    12    13    14    15    16    17                     │
│   ──────────────────────────────────────────────────         │
│   18    19    20    21    22    23    24                     │
│   ──────────────────────────────────────────────────         │
│   25    26    27    28    29    30    31                     │
│   ──────────────────────────────────────────────────         │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  ↑↓ Seleziona settimana · ↵ Apri settimana · Esc Anno       │  ← Footer
└──────────────────────────────────────────────────────────────┘
```

#### Regole visive

- **Righe settimana:** ogni riga è separata da `border-bottom: 1px solid var(--color-rule)`.
- **Settimana selezionata:** la riga riceve `background: var(--color-bg-alt)` e `border-top: 2px solid var(--color-rule-strong)` / `border-bottom: 2px solid var(--color-rule-strong)`.
- Numero del giorno: `--text-md`, `--font-body`. Giorni del mese precedente/successivo: `--color-ink-faint`.
- **Oggi:** il numero ha sfondo `--color-accent`, testo `--color-bg`, dimensioni fisse `28×28px`, quadrato.
- **Festività:** piccola stella `icon-star` a fianco del numero, `12px`, `--color-holiday`.
- Le celle non mostrano testo degli eventi — solo il numero del giorno e l'indicatore festività.
- Giorni con almeno un evento: un trattino `—` sotto il numero, `--color-ink-muted`, centrato.

---

### 3. Vista Settimanale *(schermata principale)*

**Scopo:** visione d'insieme della settimana con gli appuntamenti. Permette di selezionare un giorno o un singolo appuntamento.  
**Navigazione:** Su/Giù naviga tra gli appuntamenti visibili (o tra i giorni se nessun appuntamento); Invio entra nel dettaglio appuntamento o nella vista giornaliera; Esci torna alla vista mensile.

#### Layout

```
┌───────────────────────────────────────────────────────────────────────┐
│  ← Esci   Settimana 21 · 18–24 Maggio 2026         [icona-settimana] │  ← Header
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│   ORA  │  LUN 18  │  MAR 19  │  MER 20  │  GIO 21 ◄══│  VEN 22  │… │
│   ─────┼──────────┼──────────┼──────────┼────────────┼──────────┤   │
│  08:00 │          │          │  Riunione│            │          │   │
│        │          │          │  09:00   │            │          │   │
│  09:00 │          │          │  ────────│            │          │   │
│  10:00 │ Dentista │          │          │ Videocall  │          │   │
│        │ 10:30    │          │          │ 10:00      │          │   │
│  11:00 │ ─────────│          │          │ ────────── │          │   │
│  12:00 │          │  Pranzo  │          │            │  Pranzo  │   │
│        │          │  12:30   │          │            │  12:00   │   │
│  ...   │  ...     │  ...     │  ...     │  ...       │  ...     │   │
│                                                                       │
├───────────────────────────────────────────────────────────────────────┤
│  ↑↓ Naviga appuntamenti · ↵ Dettaglio · Esc Mese                     │  ← Footer
└───────────────────────────────────────────────────────────────────────┘
```

#### Regole visive

- **Colonna ORA:** larghezza fissa `52px`, orari in `--font-mono`, `--text-xs`, `--color-ink-muted`.
- **Colonne giorno:** larghezza uniforme, calcolata per riempire esattamente la content area senza scrolling orizzontale. La riga dell'ora corrente è indicata da una linea `1px solid var(--color-accent)` orizzontale.
- **Intestazione colonna giorno:** giorno della settimana (3 lettere, uppercase) + numero. Il giorno corrente: inversione cromatica (sfondo `--color-accent`, testo `--color-bg`). Il giorno selezionato: `border-bottom: 2px solid var(--color-rule-strong)`.
- **Blocco appuntamento:** rettangolo netto con `border: 1px solid var(--color-rule-strong)`, sfondo `--color-bg-alt`. Il testo interno: nome evento in `--text-sm` bold + orario inizio in `--text-xs mono`.
- **Appuntamento selezionato:** `border: 2px solid var(--color-rule-strong)`, sfondo `--color-accent`, testo `--color-bg`.
- **Appuntamenti tutto-il-giorno:** fascia fissa sopra la griglia oraria, altezza `24px`, separata da `border-bottom: 1px solid var(--color-rule-strong)`.
- **Griglia temporale:** la vista copre 08:00–22:00 di default (configurabile). Se un evento cade fuori finestra, appare come blocco troncato con ellissi `…` nell'intestazione.

---

### 4. Vista Giornaliera

**Scopo:** dettaglio di un singolo giorno. Permette di selezionare un singolo appuntamento.  
**Navigazione:** Su/Giù seleziona l'appuntamento; Invio entra nel dettaglio; Esci torna alla vista settimanale.

#### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ← Esci   Giovedì, 21 Maggio 2026               [icona-day] │  ← Header
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  09:00 ──────────────────────────────────────────────────── │
│         Videocall con il team                                │
│         09:00 – 10:00                                        │
│                                                              │
│  12:30 ──────────────────────────────────────────────────── │
│         Pranzo con Marco                                     │
│         12:30 – 14:00                               ◄══ SEL │
│                                                              │
│  15:00 ──────────────────────────────────────────────────── │
│         Firma documenti notarili                             │
│         15:00 – 15:30  ★ Festività prossima                 │
│                                                              │
│  (nessun altro appuntamento)                                 │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  ↑↓ Seleziona · ↵ Dettaglio · Esc Settimana                 │  ← Footer
└──────────────────────────────────────────────────────────────┘
```

#### Regole visive

- Ogni appuntamento occupa un blocco verticale separato da `border-top: 1px solid var(--color-rule)`.
- L'orario è mostrato nella fascia sinistra (larghezza fissa `56px`), in `--font-mono`, `--text-sm`, `--color-ink-muted`, allineato a destra.
- Nome evento: `--font-body`, `--text-base`, `font-weight: 600`.
- Intervallo orario completo: `--text-sm`, `--color-ink-muted`, sotto il nome.
- **Appuntamento selezionato:** `background: var(--color-bg-alt)`, `border-left: 3px solid var(--color-rule-strong)`.
- Il layout è calcolato per mostrare al massimo gli appuntamenti che rientrano nella content area. Se gli appuntamenti sono più del visibile, vengono compressi uniformemente (senza scrolling): la selezione con Su/Giù fa avanzare la visualizzazione sostituendo l'intero contenuto (effetto "pagina").
- Slot vuoti tra appuntamenti: mostrati come riga `──── Libero ────` in `--color-ink-faint`, `--text-xs`, solo se lo spazio temporale libero è ≥ 60 minuti.

---

### 5. Vista Dettaglio Appuntamento

**Scopo:** mostrare tutte le informazioni di un singolo appuntamento. **Unica schermata con scrolling.**  
**Navigazione:** Su/Giù scrolla il contenuto se necessario; Esci torna alla schermata precedente (giornaliera o settimanale). Il tasto Invio non ha effetto.

#### Layout

```
┌──────────────────────────────────────────────────────────────┐
│  ← Esci   Dettaglio Appuntamento           [icona-evento]    │  ← Header
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  ════════════════════════════════════════════════════════    │
│  PRANZO CON MARCO                                            │
│  ════════════════════════════════════════════════════════    │
│                                                              │
│  [icona-clock]   Giovedì, 21 Maggio 2026                    │
│                  12:30 – 14:00  (1h 30min)                  │
│                                                              │
│  [icona-map-pin] Ristorante Al Porto                        │
│                  Via dei Pini, 14 — Milano                  │
│                                                              │
│  [icona-users]   Marco Bianchi, Anna Rossi                  │
│                                                              │
│  [icona-repeat]  Non ricorrente                             │
│                                                              │
│  ────────────────────────────────────────────────────────── │
│  NOTE                                                        │
│  Portare la documentazione del contratto.                   │
│  Confermare prenotazione entro stamattina.                  │
│  ...                       ← scrolling solo in questa area  │
│                                                              │
├──────────────────────────────────────────────────────────────┤
│  ↑↓ Scorri · Esc Ritorna                                     │  ← Footer
└──────────────────────────────────────────────────────────────┘
```

#### Regole visive

- Titolo dell'evento: `--font-display`, `--text-xl`, uppercase, `font-weight: bold`. Separato da doppie righe `════` (carattere `U+2550`) sopra e sotto — stile divisore di giornale.
- Ogni riga informativa: icona Tabler `16px` + testo in `--font-body`, `--text-base`. Le righe sono separate da spazio verticale `12px`, senza bordi.
- La sezione **NOTE** è separata da `border-top: 1px solid var(--color-rule)`. È l'unica area scrollabile: overflow visibile tramite un indicatore `▼` in `--color-ink-faint` nell'angolo inferiore destro del blocco note, quando il testo supera lo spazio disponibile.
- Nel footer, il tasto "Esci" è evidenziato con `font-weight: bold` come unica azione disponibile; gli altri tre tasti sono in `--color-ink-faint`.

---

## Flusso di Navigazione

```
Vista Annuale
     │  ↵ (seleziona mese)
     ▼
Vista Mensile  ←──── Esc ────┐
     │  ↵ (seleziona settimana)  │
     ▼                           │
Vista Settimanale ←─── Esc ──┤
     │  ↵ (seleziona giorno      │
     │      o appuntamento)      │
     ├──────────────┐            │
     ▼              ▼            │
Vista Giornaliera  Dettaglio    │
     │  ↵            Appuntamento│
     ▼  (seleziona   ↑↓ scroll   │
  Dettaglio          Esc ────────┘
  Appuntamento
```

---

## Indicatori di Stato (Header)

L'header di ogni schermata (eccetto la vista annuale) mostra, a destra, tre piccoli indicatori in `--text-xs`:

| Indicatore | Contenuto |
|---|---|
| Tipo display | `e-ink` / `hdmi` — testo fisso |
| Modalità colore | `☀ Giorno` / `☾ Notte` — solo hdmi |
| Ora corrente | `HH:MM` — aggiornato ad ogni refresh |

---

## Comportamento E-Ink Specifico

Quando `display.type = "eink"`:

1. **Palette:** il renderer usa solo i valori quantizzati della palette del modello configurato. I colori sopra sono scelti per mappare in modo deterministico.
2. **Nessuna modalità notte:** l'interfaccia è sempre in modalità giorno. Il toggle notte è nascosto.
3. **Footer non interattivo:** il footer mostra la legenda testuale identica a quella HDMI, ma i tasti non sono cliccabili. I pulsanti fisici sono l'unico mezzo di interazione.
4. **Dithering:** il post-processor applica Floyd-Steinberg alle aree di testo piccolo per migliorare la leggibilità su display a bassa risoluzione.
5. **Refresh parziale:** il layout è strutturato per isolare le aree che cambiano (content area) da quelle statiche (header, footer), per supportare il partial refresh delle librerie Waveshare.

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
  --height-header: 56px;
  --height-footer: 40px;
  --border-radius: 0;           /* Mai arrotondare */
  --shadow:        none;        /* Mai ombreggiare */
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
