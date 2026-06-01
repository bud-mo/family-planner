# Design - Family Planner Calendar

## Design Philosophy

The calendar is conceived as an **interactive printed page**, not as a classic digital application. The aesthetic reference is *The Wall Street Journal*: rigorous typography, visual hierarchy built exclusively through font weight, size, and white space. No superfluous decorative elements.

**Core principles:**

- Total absence of shadows (`box-shadow`, `text-shadow`, `drop-shadow`)
- No rounded corners (`border-radius: 0` everywhere)
- No animation or transition - updates are instantaneous
- The layout never scrolls
- The grid is the only composition tool

---

## Typography

### Font Stack

| Role | Family | Style |
|---|---|---|
| Titles and headings | **Playfair Display** | Regular / Bold |
| Body and data | **IBM Plex Sans** | Regular / Medium / SemiBold |
| Description italics | **IBM Plex Sans** | Italic |
| Monospace (times) | **IBM Plex Mono** | Regular |

All families are from the Google Fonts catalog, optimized for screen rendering, including e-ink. Universal fallback is `serif` for headings and `sans-serif` for body text.

```css
--font-display: 'Playfair Display', Georgia, serif;
--font-body:    'IBM Plex Sans', Helvetica Neue, Arial, sans-serif;
--font-mono:    'IBM Plex Mono', Courier New, monospace;
```

### Typographic Scale

The scale is fixed in pixels to guarantee consistency on physical displays (no viewport-dependent `rem`). Values are calibrated for high-resolution displays (Inky Impression 13.3" 1600x1200 and similar):

| Token | Size | Usage |
|---|---|---|
| `--text-xs`  | 18px | Secondary labels, notes, times |
| `--text-sm`  | 21px | Appointment metadata, hourly temperature |
| `--text-base`| 24px | Body text, event names |
| `--text-md`  | 28px | Selected day number |
| `--text-lg`  | 38px | Date in weather banner, calendar heading |
| `--text-xl`  | 50px | Section title, prominent element |
| `--text-2xl` | 76px | Exceptional usage |

Uniform line-height: `1.3`. Heading letter-spacing: `0.03em`.

---

## Color Palette

### Day Mode (default - e-ink and HDMI)

The palette is limited to **six values** to guarantee fidelity on grayscale e-ink and color displays.

```css
/* Background */
--color-bg:          #FFFFFF;   /* pure white - maximum contrast on e-ink */
--color-bg-alt:      #EEECE6;   /* very light gray - alternating rows, bands */

/* Text */
--color-ink:         #111111;   /* near-black */
--color-ink-muted:   #666666;   /* medium gray - metadata, past times */
--color-ink-faint:   #AAAAAA;   /* light gray - separators, placeholders */

/* Accents */
--color-accent:      #1A1A1A;   /* near-black - selection, today */
--color-holiday:     #444444;   /* dark gray - holiday highlight */

/* Borders */
--color-rule:        #CCCCAA;   /* sepia-toned line - horizontal dividers */
--color-rule-strong: #333333;   /* dark line - selected element border */

/* Weather icons */
--weather-sun:   #F5A623;   /* sun / clear sky */
--weather-cloud: #9CA3AF;   /* cloud / overcast / fog */
--weather-rain:  #3B82F6;   /* rain / showers / thunderstorm */
--weather-snow:  #93C5FD;   /* snow / hail */
```

**On e-ink:** the renderer automatically quantizes to the physical panel palette. The colors above are chosen to map deterministically.

### Spectra 6 Palette (Pimoroni Inky Impression)

When `eink_palette: "spectra6"` is configured, the post-processor quantizes to the 6-color palette of the Pimoroni Inky Impression panel. `PillowEinkRenderer` still generates a standard RGB image; `EinkRenderer` converts it to palette mode `"P"` before sending it to hardware.

| Index | Name | RGB | Usage |
|---|---|---|---|
| 0 | Black | `#000000` | Text, borders |
| 1 | White | `#FFFFFF` | Background |
| 2 | Red | `#FF0000` | Accents, weather icon `sun` |
| 3 | Green | `#00FF00` | (reserved) |
| 4 | Blue | `#0000FF` | Weather icon `cloud-rain` |
| 5 | Yellow | `#FFFF00` | (reserved) |

Floyd-Steinberg dithering (`eink_dither: true`) is recommended with this palette to soften color transitions in photos and gradient areas.

### Weather Icon Palette

Weather icons are tinted with condition-specific colors (instead of `--color-ink`), defined in [app/renderer/tokens.py](app/renderer/tokens.py) as `WEATHER_ICON_COLORS`. This applies both to the main icon in the top banner and to the icons in the hourly strip.

| Token | Value | Condition |
|---|---|---|
| `--weather-sun` | `#F5A623` | Sun, clear sky |
| `--weather-cloud` | `#9CA3AF` | Cloud, fog, overcast |
| `--weather-rain` | `#3B82F6` | Rain, showers, thunderstorm |
| `--weather-snow` | `#93C5FD` | Snow, hail |

---

## Iconography - Tabler Icons

The adopted icon set is **Tabler Icons** (SVG outline version, stroke-width `1.5px`). Icons are always monochromatic, tinted through `currentColor`.

| Tabler Icon | Usage |
|---|---|
| `icon-sun` | Sunny condition - weather banner / day mode indicator |
| `icon-cloud` | Cloudy condition - weather banner |
| `icon-cloud-rain` | Rainy condition - weather banner |
| `icon-snowflake` | Snow condition - weather banner |
| `icon-chevron-up` | Up button (footer) |
| `icon-chevron-down` | Down button (footer) |
| `icon-corner-up-left` | Today / Return button (footer) |
| `icon-check` | Enter button - disabled (footer) |
| `icon-clock` | Appointment time - list |
| `icon-map-pin` | Appointment location - list |
| `icon-star` | Holiday / Special day - monthly calendar |

Standard icon sizes: `16px` (inline with text) / `20px` (buttons) / `24px` (view headers) / `48px` (weather banner icon).

---

## Overall Layout

The interface consists of a single **Home screen** with two layout variants selectable via configuration. There is no separate header: the date is embedded in the weather banner.

### Portrait Layout

Four stacked horizontal bands:

```
┌──────────────────────────────────────────────────────────┐
│  WEATHER BANNER (fixed height: 217px)                   │
│  Date · Weather icon · Current temperature · Max/Min    │
│  ──────────────────────────────────────────────────────  │
│  Hourly forecast: 6 cells · 48px icon · Temp            │
├──────────────────────────────────────────────────────────┤
│  MONTHLY CALENDAR (fixed height: 560px)                 │
│  Visual monthly view - no interaction                   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  APPOINTMENT LIST (variable height)                      │
│  From the next appointment onward - Agenda style         │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  FOOTER (fixed height: 54px)                             │
│  Status indicators                                       │
└──────────────────────────────────────────────────────────┘
```

**Weather Banner:** `border-bottom: 2px solid var(--color-rule-strong)`.  
**Monthly Calendar:** `border-bottom: 1px solid var(--color-rule-strong)`.  
**Appointment List:** takes remaining height (`height − 217px − 560px − 54px`). No scrolling.  
**Footer:** `border-top: 1px solid var(--color-rule)`. Shows only status indicators on the right (no navigation buttons).

### Landscape Layout

Two side-by-side columns + full-width footer:

```
┌───────────────────────────────┬────────────────────────────────────────┐
│  LEFT COLUMN (50%)            │  RIGHT COLUMN (50%)                    │
│                               │                                        │
│  WEATHER (217px)              │  APPOINTMENT LIST                      │
│  Date · Icon · Temperature    │  (full content area height)            │
│  Hourly forecasts (6 cells)   │                                        │
│  ───────────────────────────  │                                        │
│  MONTHLY CALENDAR             │                                        │
│  (remaining height)           │                                        │
│                               │                                        │
├───────────────────────────────┴────────────────────────────────────────┤
│  FOOTER (54px, full width)                                              │
└──────────────────────────────────────────────────────────────────────────┘
```

**Column separator:** `border-right: 1px solid var(--color-rule-strong)` on the left column, height `height − 54px`.  
**Weather section:** `border-bottom: 1px solid var(--color-rule)`.  
**Left column:** width `50%` (exact half). Example: 1024x600 -> 512px left, 512px right; 1600x1200 -> 800px left, 800px right.  
**Appointment List:** occupies full content area height (`height − 54px`).  
**Footer:** `border-top: 1px solid var(--color-rule)`. Full width, shows only status indicators on the right.

The footer is the fixed bottom band (height `54px`). It contains no navigation buttons. It shows only the **status indicators** right-aligned, in `--text-xs`, `--color-ink-muted`:

| Indicator | Content |
|---|---|
| Display type | `e-ink` / `hdmi` - fixed text |
| Layout | `portrait` / `landscape` - fixed text |
| Current time | `HH:MM` - updated at every refresh |

```
┌──────────────────────────────────────────────────────────────┐
│                                 hdmi · landscape · 09:32    │
└──────────────────────────────────────────────────────────────┘
```

---

## Screens

---

### Home (single screen)

**Goal:** show weather conditions, current monthly calendar, and appointment list from the next item onward, all at a glance.  
**Navigation:** Up/Down paginates the appointment list; Esc resets to today; Enter disabled.

#### Weather Section

Top banner in portrait, top section of the left column in landscape.

```
┌──────────────────────────────────────────────────────────────┐
│  Sunday, 24 May 2026                 ⛅   18°  ↑22°         │
│                                              ↓14°           │
└──────────────────────────────────────────────────────────────┘
```

The right side is a three-subcolumn block aligned to the right margin:

- **Subcolumn 1 (left):** Tabler weather-condition icon `48px`, tinted with the weather color palette (`--weather-*`), vertically centered in the banner
- **Subcolumn 2 (center):** current temperature, `--font-body`, `40px`, `font-weight: 600`, `--color-ink`, vertically centered, right-anchored
- **Subcolumn 3 (right):** max and min stacked vertically, `--font-body`, `--text-xs` (18px), `--color-ink-muted`, both right-anchored; `↑max` at one-third of banner height, `↓min` at two-thirds
- **Left side:** date, `--font-display`, `--text-lg`, format `"Weekday, DD Month YYYY"`, `--color-ink`
- Background: `--color-bg` - no alternating background in the banner
- Weather data refresh: every hour (provider TTL cache)

**Hourly forecast strip** (below date/weather band, height 127px):

```
┌────────┬────────┬────────┬────────┬────────┬────────┐
│ 14:00  │ 16:00  │ 18:00  │ 20:00  │ 22:00  │ 00:00  │
│   ⛅    │   ☁    │   🌧    │   ⛅    │   ⛅    │   ☁    │
│  18°   │  17°   │  15°   │  14°   │  13°   │  12°   │
└────────┴────────┴────────┴────────┴────────┴────────┘
```

- **6 cells** of equal width (`width / 6`): current slot + 5 subsequent slots (every 2 hours)
- **Time** (row 1, top-centered): `--font-mono`, `--text-xs` (18px), `--color-ink-muted`, `mt` anchor 4px from cell top edge
- **Icon** (row 2, centered vertically between time and temperature): Tabler `48px`, tinted with weather color palette (`--weather-*`), horizontally centered in cell
- **Temperature** (row 3, bottom-centered): `--font-body` SemiBold, `--text-sm` (21px), `--color-ink`, baseline anchored 27px from cell bottom edge
- **Vertical separators** between cells: `1px solid var(--color-rule)` (not on outer edges)

#### Monthly Calendar Section

The monthly calendar is **purely visual** - it does not respond to user interaction.

```
┌──────────────────────────────────────────────────────────────┐
│                        MAY 2026                              │
│  MON   TUE   WED   THU   FRI   SAT   SUN                     │
│   27    28    29    30     1     2     3                     │
│    4     5     6     7     8     9    10                     │
│   11    12    13    14    15    16    17                     │
│   18    19    20    21    22    23   [24]                    │
│   25    26    27    28    29    30    31                     │
└──────────────────────────────────────────────────────────────┘
```

**Visual rules:**

- Month heading: `--font-body`, `--text-sm`, uppercase, `letter-spacing: 0.08em`, centered
- Column headers (M T W T F S S): `--text-xs`, `--color-ink-muted`
- Day numbers: `--text-xs`, `--font-body`, `--color-ink`
- **Today:** `--color-bg-alt` background on the whole cell; day number and event text in `--color-ink` (no square, no inversion)
- **Holidays:** number in `--font-display`, `font-weight: bold`, `--color-holiday`
- Previous/next month days: `--color-ink-faint`, no events shown
- **Cell layout:** day number in top band (18px); event lines in lower band
- **Event lines:** `--font-body`, `--text-xs`, `--color-ink-muted`; format `HH:MM Title` for timed events, title only for all-day; text truncated with `…` if it does not fit width
- **Overflow:** if events do not all fit, last line shows `+N` in `--color-ink-faint`
- **Per-cell sorting:** all-day first, then by start time

#### Appointment List Section

Agenda-style list inspired by Google Calendar. The date for each day is shown in a **fixed left column** (84px), not as a horizontal separator. The first event of each day shows day number and abbreviated weekday on the same row as the title; subsequent events that day leave the date column empty. Each row has a **colored dot** at the start of the time area indicating the source calendar. Up/Down pagination replaces the entire page - no CSS scrolling.

```
┌────────────────────────────────────────────────────────────────┐
│  24 SUN      ●  All day          Team meeting                 │
│             ●  15:00 - 16:00    Dentist                       │
│           ──────────────────────────────────────────────────   │
│             ●  17:30 - 18:30    Appointment                   │
│                Room B                                          │
├────────────────────────────────────────────────────────────────┤
│  25 MON      ●  09:00 - 10:00    Client video call            │
│             ●  12:30 - 13:30    Lunch with Marco              │
│                Al Porto Restaurant                             │
└────────────────────────────────────────────────────────────────┘
```

> The small space before the dot (8px) is the left padding of the time area; an equal padding (8px) separates the end of the time area from the start of the title.

**Visual rules:**

- **Date column (84px, left):**
  - **Single row** at the same height as event title (`y = y0+30`): day number (`--font-body`, `--text-md`, `--color-ink`) + abbreviated weekday (`--font-body` SemiBold, `--text-xs`, `--color-ink-muted`), both right-aligned in the column
  - Day number is placed at a fixed offset from the right of the column, calculated on the maximum width of weekday abbreviations (`MON…SUN`) - this guarantees vertical alignment across different rows
  - Format: `"31"` + `"SUN"` (abbreviated weekday only, no month)
  - Shown only for the **first event of each day**; subsequent rows leave the column empty
- **Time + dot column (200px):**
  - **8px left padding** between right edge of date column and left-center of the dot
  - Dot (● 14px diameter): filled circle, vertically centered in row; colored with `evt.color`; if undefined uses `--color-rule`
  - Time: `--font-mono`, `--text-xs`, `--color-ink`, left-aligned to the right of the dot (6px gap), vertically centered; format `"HH:MM - HH:MM"` on one line
  - **8px right padding** between right edge of time column and event title
- **All-day event:** replaces time with `"All day"` in `--font-mono`, `--text-xs`, `--color-ink`, to the right of the dot, vertically centered
- **Content (title + location):**
  - Event name: `--font-body`, `--text-base`, `font-weight: 600`, `--color-ink`
  - Location (if present): `--text-xs`, `--color-ink-muted`, on a separate line below the name
- **Event separator:** `1px solid var(--color-rule-strong)` above the **first row of each day** (day boundary); subsequent events of the same day have no separator - the 30px top margin and date column provide sufficient visual separation, even on BW e-ink displays where `--color-rule` (#CCCCAA, luminance about 200) disappears during quantization
- **Empty list:** centered text `"No appointments"`, `--color-ink-faint`, `--text-sm`

**Row heights (dynamic):**

| Row type | Formula | Example |
|---|---|---|
| Event without location and without description | 60 px | 60 px |
| Event with location only | 60 + 14 = 74 px | 74 px |
| Event with N description lines (without location) | 60 + N x 22 + 8 px | 1 line -> 90 px, 3 lines -> 134 px |
| Event with location and N description lines | 60 + 14 + N x 22 + 8 px | 1 line -> 104 px, 10 lines -> 312 px |

The final 8px (only when a description is present) adds bottom breathing room equivalent to the white space above the title glyph.

**Description formatting (rich text HTML):**

Descriptions can include HTML from CalDAV sources. The renderer interprets the following tags:

| HTML Tag | Visual Effect |
|---|---|
| `<b>`, `<strong>` | Text in IBM Plex Sans SemiBold |
| `<i>`, `<em>` | Text in IBM Plex Sans Italic |
| `<u>` | Text with underlying horizontal line (1 px, `--color-ink-faint`) |
| `<a href="...">` | Text in `--color-ink-muted` + underline |
| `<br>`, `</p>`, `</div>`, `</li>` | Line break |
| `<ul><li>` | Line with `• ` prefix |
| `<ol><li>` | Line with `N. ` prefix (progressive counter) |

Unrecognized tags are silently removed. Plain text (without tags) is split on `\n`. Each line is truncated with `…` if it exceeds available width.

---

## Navigation Flow

The interface has a single screen. There is no navigation - the current day is always shown.

---

## Status Indicators (Footer)

Status indicators are built into the right side of the footer, in `--text-xs`, `--color-ink-muted`:

| Indicator | Content |
|---|---|
| Display type | `e-ink` / `hdmi` - fixed text |
| Layout | `portrait` / `landscape` - fixed text |
| Current time | `HH:MM` - updated at every refresh |

---

## E-Ink Specific Behavior

When `display.type = "eink"`:

1. **Palette:** the renderer uses only quantized values from the configured model palette. The colors above are chosen to map deterministically.
2. **Non-interactive footer:** the footer shows the same textual legend as HDMI, but keys are not clickable. Physical buttons are the only interaction method.
3. **Dithering:** the post-processor applies Floyd-Steinberg to small text areas to improve readability on low-resolution displays.
4. **Partial refresh:** in landscape layout, the monthly calendar (left column, bottom section) is the most static area and ideal for separate partial refresh. The appointment list (right column / lower portrait area) changes at each navigation action.
5. **Rotation:** `display.rotation` (0 / 90 / 180 / 270 degrees) is applied by `EinkRenderer` as the final post-processing step. The logical canvas generated by `PillowEinkRenderer` is always `display.width x display.height`; for 90/270 rotations, dimensions are swapped before resize.

### Physical Buttons (Inky Impression)

| Button | Action |
|---|---|
| **A** | Return to planner screen (exit artwork mode) |
| **B** | Show artwork mode (random painting - privacy) |
| **D** | Shutdown - show final artwork on panel, then power off |

### Supported Models

| `eink_model` | Driver | Resolution | Palette |
|---|---|---|---|
| `7in5_V2` | `waveshare_epd.epd7in5_V2` | 800x480 | `bw`, `bwr`, `4gray` |
| `7in5` | `waveshare_epd.epd7in5` | 640x384 | `bw`, `bwr` |
| `4in2` / `4in2_V2` | `waveshare_epd.epd4in2*` | 400x300 | `bw`, `bwr` |
| `5in83_V2` | `waveshare_epd.epd5in83_V2` | 648x480 | `bw`, `bwr`, `4gray` |
| `3in7` | `waveshare_epd.epd3in7` | 280x480 | `4gray` |
| `inky_impression_4` | `inky` (Pimoroni) | 600x400 | `spectra6` |
| `inky_impression_7` | `inky` (Pimoroni) | 800x480 | `spectra6` |
| `inky_impression_13` | `inky` (Pimoroni) | 1600x1200 | `spectra6` |

### Pimoroni Inky Impression (Spectra 6)

`inky_impression_*` models use the `InkyDisplay` class (instead of `EinkDisplay`) through Pimoroni's `inky` library. The rendering pipeline is identical: `PillowEinkRenderer` -> `EinkRenderer.process()` (`spectra6` quantization) -> `InkyDisplay.push()`.

**`_busy_wait` fix for Inky 13.3":** version 2.4.0 of the `inky` library has a bug in `_busy_wait()` for the EL133UF1 panel (BUSY is active-low, but loop condition is inverted). `InkyDisplay.push()` fixes this bug by replacing `_busy_wait()` on the instance with a correct implementation before calling `show()`.

---

## Artwork Screen (Privacy Mode)

**Goal:** hide the family calendar in the presence of guests or when the device is unattended, replacing it with a public-domain painting from the **Art Institute of Chicago**.

**Activation:** **B** button (Inky Impression) / `B` key (pygame HDMI).

**Layout:**

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│      Painting (full-bleed crop, ImageOps.fit)        │
│                                                      │
│                                                      │
├──────────────────────────────────────────────────────┤
│      Title, Artist (Year)                            │  <- centered caption
└──────────────────────────────────────────────────────┘
```

**Visual rules:**

- **Full-bleed** painting (`ImageOps.fit`): covers the entire display, preserving proportions with centered crop (LANCZOS)
- **Caption** (optional, if metadata is available): solid `BG` rectangle, top border `1px INK_MUTED`, text `"Title, Artist (Year)"` in `--font-body` Italic, `--text-xs`, `--color-ink`
  - Horizontally centered; positioned `30px` from display bottom edge
  - Maximum width 80% of display (`MAX_W = W x 0.80`); truncated with `…` if exceeded
  - Padding: `16px` horizontal, `7px` vertical
- **No other UI elements:** no banners, calendars, footer, or status indicators
- **On e-ink:** painting passes through `EinkRenderer.process()` - palette quantization + dithering (`eink_dither: true` recommended)

**Return to planner:** **A** button (e-ink) / `A` HDMI -> planner resumes immediately.

---

## Shutdown Screen

**Goal:** leave a visually pleasing image on the e-ink panel (instead of a blank white screen) before shutting down the Raspberry Pi.

**Activation:** **D** button (Inky Impression) / `D` key (pygame HDMI).

**Behavior:** identical to artwork screen - same query, same full-bleed layout with caption. The panel keeps the image after shutdown (e-ink is bistable).

---

```css
:root {
  /* Typography */
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

  /* Colors (day mode) */
  --color-bg:          #FFFFFF;
  --color-bg-alt:      #EEECE6;
  --color-ink:         #111111;
  --color-ink-muted:   #666666;
  --color-ink-faint:   #AAAAAA;
  --color-accent:      #1A1A1A;
  --color-holiday:     #444444;
  --color-rule:        #CCCCAA;
  --color-rule-strong: #333333;

  /* Structure */
  --height-banner-main:   90px;      /* Top band: date and current weather */
  --height-banner-hourly: 127px;     /* Bottom band: hourly forecasts */
  --height-banner:        217px;     /* Total weather banner (portrait) / weather section (landscape) */
  --height-calendar:      560px;     /* Monthly calendar: 4 event rows per cell (portrait only) */
  --height-footer:        54px;
  --col-left-ratio:       50%;       /* Left column width in landscape */
  --border-radius:        0;         /* Never round corners */
  --shadow:               none;      /* Never use shadows */
}
```

---

## Target Displays

Pixel-specific values for supported displays:

| Display | Resolution | Default layout | Left column | Right column | Appointment list |
|---|---|---|---|---|---|
| HDMI 7" | 1024x600 | `landscape` | 512px | 512px | 546px height |
| Inky Impression 13.3" | 1600x1200 | `landscape` | 800px | 800px | 1146px height |
| HDMI portrait (rotated) | 600x1024 | `portrait` | - | - | 193px height |
| E-ink portrait (rotated) | 1200x1600 | `portrait` | - | - | 769px height |

Portrait calculations: list = `height − 217px − 560px − 54px`.  
Landscape calculations: list height = `height − 54px`; left column = `width x 0.50`.

---

## Layout Configuration

Layout is selected via the `display.layout` field in the YAML config file:

```yaml
display:
  layout: "landscape"   # "landscape" | "portrait"
  eink_model: "inky_impression_13"   # see supported models table
  eink_palette: "spectra6"           # "bw" | "bwr" | "4gray" | "spectra6"
  eink_dither: true                   # Floyd-Steinberg dithering
  eink_saturation: 0.5                # color saturation for spectra6 palette (0.0-1.0)
```

The HTML template applies a corresponding CSS class on the `<body>` tag:

```html
<body class="layout-landscape">
<!-- or -->
<body class="layout-portrait">
```

The two classes select their respective CSS blocks (column flexbox for landscape, vertical stack for portrait). `PillowEinkRenderer` reads `config.display.layout` to select the corresponding rendering method.
# Design - Family Planner Calendar

## Design Philosophy

The calendar is conceived as an **interactive printed page**, not as a classic digital application. The aesthetic reference is *The Wall Street Journal*: rigorous typography, visual hierarchy built exclusively through font weight, size, and whitespace. No superfluous decorative elements.

**Core principles:**

- Total absence of shadows (`box-shadow`, `text-shadow`, `drop-shadow`)
- No rounded corners (`border-radius: 0` everywhere)
- No animations or transitions - updates are instantaneous
- The layout never scrolls
- The grid is the only composition tool

---

## Typography

### Font Stack

| Role | Family | Style |
|---|---|---|
| Titles and headings | **Playfair Display** | Regular / Bold |
| Body and data | **IBM Plex Sans** | Regular / Medium / SemiBold |
| Description italics | **IBM Plex Sans** | Italic |
| Monospace (times) | **IBM Plex Mono** | Regular |

All families are part of the Google Fonts catalog, optimized for screen rendering, including e-ink. The universal fallback is `serif` for headings and `sans-serif` for body text.

```css
--font-display: 'Playfair Display', Georgia, serif;
--font-body:    'IBM Plex Sans', Helvetica Neue, Arial, sans-serif;
--font-mono:    'IBM Plex Mono', Courier New, monospace;
```

### Typographic Scale

The scale is fixed in pixels to ensure consistency on physical displays (no viewport-dependent `rem`). Values are calibrated for high-resolution displays (Inky Impression 13.3" 1600x1200 and similar):

| Token | Size | Usage |
|---|---|---|
| `--text-xs`  | 18px | Secondary labels, notes, times |
| `--text-sm`  | 21px | Appointment metadata, bi-hourly temperature |
| `--text-base`| 24px | Body text, event names |
| `--text-md`  | 28px | Selected day number |
| `--text-lg`  | 38px | Date in weather banner, calendar header |
| `--text-xl`  | 50px | Section title, prominent element |
| `--text-2xl` | 76px | Exceptional use |

Uniform line-height: `1.3`. Heading letter-spacing: `0.03em`.

---

## Color Palette

### Day Mode (default - e-ink and HDMI)

The palette is limited to **six values** to ensure fidelity on grayscale e-ink and color displays.

```css
/* Background */
--color-bg:          #FFFFFF;   /* pure white - maximum contrast on e-ink */
--color-bg-alt:      #EEECE6;   /* very light gray - alternating rows, bands */

/* Text */
--color-ink:         #111111;   /* near-absolute black */
--color-ink-muted:   #666666;   /* medium gray - metadata, past times */
--color-ink-faint:   #AAAAAA;   /* light gray - separators, placeholders */

/* Accents */
--color-accent:      #1A1A1A;   /* near-black - selection, today */
--color-holiday:     #444444;   /* dark gray - holiday highlighting */

/* Borders */
--color-rule:        #CCCCAA;   /* sepia-toned line - horizontal dividers */
--color-rule-strong: #333333;   /* dark line - selected element border */
/* Weather icons */
--weather-sun:       #F5A623;   /* sun / clear sky */
--weather-cloud:     #9CA3AF;   /* cloud / overcast / fog */
--weather-rain:      #3B82F6;   /* rain / showers / thunderstorm */
--weather-snow:      #93C5FD;   /* snow / hail */
```

**On e-ink:** the renderer automatically quantizes toward the physical display palette values. The colors above are chosen to map deterministically.

### Spectra 6 Palette (Pimoroni Inky Impression)

When `eink_palette: "spectra6"` is configured, the post-processor quantizes to the 6-color Pimoroni Inky Impression panel palette. `PillowEinkRenderer` still generates a standard RGB image; `EinkRenderer` converts it to palette mode `"P"` before sending to hardware.

| Index | Name | RGB | Usage |
|---|---|---|---|
| 0 | Black | `#000000` | Text, borders |
| 1 | White | `#FFFFFF` | Background |
| 2 | Red | `#FF0000` | Accents, `sun` weather icon |
| 3 | Green | `#00FF00` | (reserved) |
| 4 | Blue | `#0000FF` | `cloud-rain` weather icon |
| 5 | Yellow | `#FFFF00` | (reserved) |

Floyd-Steinberg dithering (`eink_dither: true`) is recommended with this palette to soften color transitions in photos and gradient areas.

### Weather Icon Palette

Weather icons are tinted with condition-specific colors (instead of `--color-ink`), defined in [app/renderer/tokens.py](app/renderer/tokens.py) as `WEATHER_ICON_COLORS`. Applied both to the main icon in the top banner and to icons in the bi-hourly strip.

| Token | Value | Condition |
|---|---|---|
| `--weather-sun` | `#F5A623` | Sun, clear sky |
| `--weather-cloud` | `#9CA3AF` | Cloud, fog, overcast |
| `--weather-rain` | `#3B82F6` | Rain, showers, thunderstorm |
| `--weather-snow` | `#93C5FD` | Snow, hail |

---

## Iconography - Tabler Icons

The adopted icon set is **Tabler Icons** (SVG outline version, stroke-width `1.5px`). Icons are always monochrome, colored through `currentColor`.

| Tabler icon | Usage |
|---|---|
| `icon-sun` | Sunny condition - weather banner / day mode indicator |
| `icon-cloud` | Cloudy condition - weather banner |
| `icon-cloud-rain` | Rainy condition - weather banner |
| `icon-snowflake` | Snow condition - weather banner |
| `icon-chevron-up` | Up button (footer) |
| `icon-chevron-down` | Down button (footer) |
| `icon-corner-up-left` | Today / Return button (footer) |
| `icon-check` | Enter button - disabled (footer) |
| `icon-clock` | Appointment time - list |
| `icon-map-pin` | Appointment location - list |
| `icon-star` | Holiday / Special day - monthly calendar |

Standard icon sizes: `16px` (inline text) / `20px` (buttons) / `24px` (view headers) / `48px` (banner weather icon).

---

## General Layout

The interface is a single **Home screen** with two layout variants selectable via configuration. There is no separate header: the date is embedded in the weather banner.

### Portrait Layout

Four stacked horizontal bands:

```
┌──────────────────────────────────────────────────────────┐
│  WEATHER BANNER (fixed height: 217px)                   │
│  Date · Weather icon · Current temp · Max/Min           │
│  ──────────────────────────────────────────────────────  │
│  Bi-hourly forecast: 6 cells · 48px icon · Temp         │
├──────────────────────────────────────────────────────────┤
│  MONTHLY CALENDAR (fixed height: 560px)                 │
│  Visual monthly view - no interaction                   │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  APPOINTMENT LIST (variable height)                      │
│  From the next appointment onward - Agenda style         │
│                                                          │
├──────────────────────────────────────────────────────────┤
│  FOOTER (fixed height: 54px)                             │
│  Status indicators                                       │
└──────────────────────────────────────────────────────────┘
```

**Weather banner:** `border-bottom: 2px solid var(--color-rule-strong)`.  
**Monthly calendar:** `border-bottom: 1px solid var(--color-rule-strong)`.  
**Appointment list:** takes the remaining height (`height - 217px - 560px - 54px`). No scrolling.  
**Footer:** `border-top: 1px solid var(--color-rule)`. Shows only right-aligned status indicators (no navigation buttons).

### Landscape Layout

Two side-by-side columns + full-width footer:

```
┌───────────────────────────────┬────────────────────────────────────────┐
│  LEFT COLUMN (50%)            │  RIGHT COLUMN (50%)                    │
│                               │                                        │
│  WEATHER (217px)              │  APPOINTMENT LIST                      │
│  Date · Icon · Temperature    │  (full content area height)            │
│  Bi-hourly forecast (6 cells) │                                        │
│  ───────────────────────────  │                                        │
│  MONTHLY CALENDAR             │                                        │
│  (remaining height)           │                                        │
│                               │                                        │
├───────────────────────────────┴────────────────────────────────────────┤
│  FOOTER (54px, full width)                                              │
└──────────────────────────────────────────────────────────────────────────┘
```

**Column separator:** `border-right: 1px solid var(--color-rule-strong)` on the left column, height `height - 54px`.  
**Weather section:** `border-bottom: 1px solid var(--color-rule)`.  
**Left column:** width `50%` (exact half). Example: 1024x600 -> 512px left, 512px right; 1600x1200 -> 800px left, 800px right.  
**Appointment list:** takes the full content area height (`height - 54px`).  
**Footer:** `border-top: 1px solid var(--color-rule)`. Full width, shows only right-aligned status indicators.

The footer is the fixed bottom band (height `54px`). It contains no navigation buttons. It exclusively shows right-aligned **status indicators**, in `--text-xs`, `--color-ink-muted`:

| Indicator | Content |
|---|---|
| Display type | `e-ink` / `hdmi` - fixed text |
| Layout | `portrait` / `landscape` - fixed text |
| Current time | `HH:MM` - updated on every refresh |

```
┌──────────────────────────────────────────────────────────────┐
│                                 hdmi · landscape · 09:32    │
└──────────────────────────────────────────────────────────────┘
```

---

## Screens

---

### Home (single screen)

**Goal:** show weather conditions, current monthly calendar, and the list of appointments from the next one onward, all at a glance.  
**Navigation:** Up/Down paginates the appointment list; Esc resets to today's date; Enter is disabled.

#### Weather Section

Top banner in portrait, upper section of left column in landscape.

```
┌──────────────────────────────────────────────────────────────┐
│  Sunday, May 24, 2026              ⛅   18°  ↑22°            │
│                                             ↓14°             │
└──────────────────────────────────────────────────────────────┘
```

The right side is a three-subcolumn block aligned to the right margin:

- **Subcolumn 1 (left):** Tabler weather condition icon `48px`, tinted with the weather color palette (`--weather-*`), vertically centered in the banner
- **Subcolumn 2 (center):** current temperature, `--font-body`, `40px`, `font-weight: 600`, `--color-ink`, vertically centered, right anchored
- **Subcolumn 3 (right):** max and min stacked vertically, `--font-body`, `--text-xs` (18px), `--color-ink-muted`, both right anchored; `↑max` at 1/3 of banner height, `↓min` at 2/3
- **Left side:** date, `--font-display`, `--text-lg`, format `"Day, DD Month YYYY"`, `--color-ink`
- Background: `--color-bg` - no alternate background in the banner
- Weather data refresh: hourly (provider TTL cache)

**Bi-hourly forecast strip** (below the date/weather band, height 127px):

```
┌────────┬────────┬────────┬────────┬────────┬────────┐
│ 14:00  │ 16:00  │ 18:00  │ 20:00  │ 22:00  │ 00:00  │
│   ⛅    │   ☁    │   🌧    │   ⛅    │   ⛅    │   ☁    │
│  18°   │  17°   │  15°   │  14°   │  13°   │  12°   │
└────────┴────────┴────────┴────────┴────────┴────────┘
```

- **6 cells** of equal width (`width / 6`): current slot + 5 subsequent slots (every 2 hours)
- **Time** (row 1, top, centered): `--font-mono`, `--text-xs` (18px), `--color-ink-muted`, `mt` anchor 4px from the top edge of the cell
- **Icon** (row 2, vertically centered between time and temperature): Tabler `48px`, tinted with the weather color palette (`--weather-*`), horizontally centered in cell
- **Temperature** (row 3, bottom, centered): `--font-body` SemiBold, `--text-sm` (21px), `--color-ink`, baseline anchored 27px from the bottom edge of the cell
- **Vertical separators** between cells: `1px solid var(--color-rule)` (not on outer edges)

#### Monthly Calendar Section

The monthly calendar is **purely visual** - it does not respond to user interaction.

```
┌──────────────────────────────────────────────────────────────┐
│                       MAY 2026                              │
│  MON   TUE   WED   THU   FRI   SAT   SUN                   │
│   27    28    29    30     1     2     3                   │
│    4     5     6     7     8     9    10                   │
│   11    12    13    14    15    16    17                   │
│   18    19    20    21    22    23   [24]                  │
│   25    26    27    28    29    30    31                   │
└──────────────────────────────────────────────────────────────┘
```

**Visual rules:**

- Month header: `--font-body`, `--text-sm`, uppercase, `letter-spacing: 0.08em`, centered
- Column headers (M T W T F S S): `--text-xs`, `--color-ink-muted`
- Day numbers: `--text-xs`, `--font-body`, `--color-ink`
- **Today:** `--color-bg-alt` background on the entire cell; day number and event text in `--color-ink` (no square, no inversion)
- **Holidays:** number in `--font-display`, `font-weight: bold`, `--color-holiday`
- Previous/next month days: `--color-ink-faint`, no events shown
- **Cell layout:** day number in the top band (18px); event lines in the lower band
- **Event lines:** `--font-body`, `--text-xs`, `--color-ink-muted`; format `HH:MM Title` for timed events, title only for all-day events; text truncated with `…` if it does not fit in width
- **Overflow:** if not all events fit, the last line shows `+N` in `--color-ink-faint`
- **Ordering per cell:** all-day first, then by start time

#### Appointment List Section

Agenda-style list inspired by Google Calendar. The date for each day is shown in a **fixed left column** (84px), not as a horizontal separator. The first event of each day shows the day number and abbreviated weekday on the same row as the title; subsequent events on that day leave the date column blank. Each row has a **colored dot** at the start of the time area indicating the source calendar. Up/Down pagination replaces the entire page - no CSS scroll.

```
┌────────────────────────────────────────────────────────────────┐
│  24 SUN      ●  All day          Team meeting                 │
│             ●  15:00 - 16:00     Dentist                      │
│           ──────────────────────────────────────────────────   │
│             ●  17:30 - 18:30     Appointment                  │
│                Room B                                          │
├────────────────────────────────────────────────────────────────┤
│  25 MON      ●  09:00 - 10:00     Client video call           │
│             ●  12:30 - 13:30     Lunch with Marco             │
│                Ristorante Al Porto                             │
└────────────────────────────────────────────────────────────────┘
```

> The small space before the dot (8px) is the left padding of the time area; an equal padding (8px) separates the end of the time field from the start of the title.

**Visual rules:**

- **Date column (84px, left):**
  - **Single line** at the same height as the event title (`y = y0+30`): day number (`--font-body`, `--text-md`, `--color-ink`) + abbreviated weekday (`--font-body` SemiBold, `--text-xs`, `--color-ink-muted`), both right-aligned within the column
  - The day number is positioned at a fixed offset from the right edge of the column, calculated from the maximum abbreviation width (`MON...SUN`) - ensures vertical alignment across different rows
  - Format: `"31"` + `"SUN"` (abbreviated weekday only, no month)
  - Shown only for the **first event of each day**; subsequent rows leave the column blank
- **Time + dot column (200px):**
  - **8px left padding** between the right edge of the date column and the center-left of the dot
  - Dot (● 14px diameter): filled circle, vertically centered in the row; colored with `evt.color`; if undefined, uses `--color-rule`
  - Time: `--font-mono`, `--text-xs`, `--color-ink`, left-aligned to the right of the dot (6px gap), vertically centered; format `"HH:MM - HH:MM"` on a single row
  - **8px right padding** between the right edge of the time column and the event title
- **All-day event:** instead of time, text `"All day"` in `--font-mono`, `--text-xs`, `--color-ink`, to the right of the dot, vertically centered in the row
- **Content (title + location):**
  - Event name: `--font-body`, `--text-base`, `font-weight: 600`, `--color-ink`
  - Location (if present): `--text-xs`, `--color-ink-muted`, on a separate row below the name
- **Event separator:** `1px solid var(--color-rule-strong)` above the **first row of each day** (day boundary); subsequent events of the same day have no separator - the 30px top margin and date column provide enough visual separation, even on BW e-ink displays where `--color-rule` (#CCCCAA, luminance ≈ 200) fades during quantization
- **Empty list:** centered text `"No appointments"`, `--color-ink-faint`, `--text-sm`

**Row heights (dynamic):**

| Row type | Formula | Example |
|---|---|---|
| Event without location and without description | 60 px | 60 px |
| Event with location only | 60 + 14 = 74 px | 74 px |
| Event with N description lines (without location) | 60 + N x 22 + 8 px | 1 line -> 90 px, 3 lines -> 134 px |
| Event with location and N description lines | 60 + 14 + N x 22 + 8 px | 1 line -> 104 px, 10 lines -> 312 px |

The final 8 px (only when a description is present) adds lower visual breathing room equivalent to the whitespace above the title glyph.

**Description formatting (rich text HTML):**

The description may contain HTML from CalDAV sources. The renderer interprets the following tags:

| HTML tag | Visual effect |
|---|---|
| `<b>`, `<strong>` | Text in IBM Plex Sans SemiBold |
| `<i>`, `<em>` | Text in IBM Plex Sans Italic |
| `<u>` | Text with an underlying horizontal line (1 px, `--color-ink-faint`) |
| `<a href="...">` | Text in `--color-ink-muted` + underline |
| `<br>`, `</p>`, `</div>`, `</li>` | Line break |
| `<ul><li>` | Line with `• ` prefix |
| `<ol><li>` | Line with `N. ` prefix (progressive counter) |

Unrecognized tags are silently removed. Plain text (without tags) is split on `\n`. Each line is truncated with `…` if it exceeds the available width.

---

## Navigation Flow

The interface has a single screen. There is no navigation - the current day is always shown.

---

## Status Indicators (Footer)

Status indicators are embedded on the right side of the footer, in `--text-xs`, `--color-ink-muted`:

| Indicator | Content |
|---|---|
| Display type | `e-ink` / `hdmi` - fixed text |
| Layout | `portrait` / `landscape` - fixed text |
| Current time | `HH:MM` - updated on every refresh |

---

## E-Ink Specific Behavior

When `display.type = "eink"`:

1. **Palette:** the renderer only uses quantized values from the configured model palette. The colors above are chosen to map deterministically.
2. **Non-interactive footer:** the footer shows the same text legend as HDMI, but keys are not clickable. Physical buttons are the only interaction method.
3. **Dithering:** the post-processor applies Floyd-Steinberg to small text areas to improve readability on low-resolution displays.
4. **Partial refresh:** in landscape layout, the monthly calendar (left column, lower section) is the most static area and ideal for separate partial refresh. The appointment list (right column / lower portrait area) changes on every navigation.
5. **Rotation:** `display.rotation` (0 / 90 / 180 / 270deg) is applied by `EinkRenderer` as the final post-processing step. The logical canvas generated by `PillowEinkRenderer` always has dimensions `display.width x display.height`; for 90/270 rotations, dimensions are swapped before resize.

### Physical Buttons (Inky Impression)

| Button | Action |
|---|---|
| **A** | Return to planner screen (exit artwork mode) |
| **B** | Show artwork mode (random painting - privacy) |
| **D** | Shutdown - show final artwork on the panel, then power off the system |

### Supported Models

| `eink_model` | Driver | Resolution | Palette |
|---|---|---|---|
| `7in5_V2` | `waveshare_epd.epd7in5_V2` | 800x480 | `bw`, `bwr`, `4gray` |
| `7in5` | `waveshare_epd.epd7in5` | 640x384 | `bw`, `bwr` |
| `4in2` / `4in2_V2` | `waveshare_epd.epd4in2*` | 400x300 | `bw`, `bwr` |
| `5in83_V2` | `waveshare_epd.epd5in83_V2` | 648x480 | `bw`, `bwr`, `4gray` |
| `3in7` | `waveshare_epd.epd3in7` | 280x480 | `4gray` |
| `inky_impression_4` | `inky` (Pimoroni) | 600x400 | `spectra6` |
| `inky_impression_7` | `inky` (Pimoroni) | 800x480 | `spectra6` |
| `inky_impression_13` | `inky` (Pimoroni) | 1600x1200 | `spectra6` |

### Pimoroni Inky Impression (Spectra 6)

`inky_impression_*` models use the `InkyDisplay` class (instead of `EinkDisplay`) based on Pimoroni's `inky` library. The rendering pipeline is identical: `PillowEinkRenderer` -> `EinkRenderer.process()` (`spectra6` quantization) -> `InkyDisplay.push()`.

**`_busy_wait` fix for Inky 13.3":** version 2.4.0 of the `inky` library has a bug in `_busy_wait()` for the EL133UF1 panel (BUSY is active-low, but the loop condition is inverted). `InkyDisplay.push()` fixes the issue by replacing `_busy_wait()` on the instance with a correct implementation before calling `show()`.

---

## Artwork Screen (Privacy Mode)

**Goal:** hide the family calendar when guests are present or when the device is unattended, replacing it with a public-domain painting from the **Art Institute of Chicago**.

**Activation:** **B** button (Inky Impression) / `B` key (pygame HDMI).

**Layout:**

```
┌──────────────────────────────────────────────────────┐
│                                                      │
│       Painting (full-bleed crop, ImageOps.fit)      │
│                                                      │
│                                                      │
├──────────────────────────────────────────────────────┤
│     Title, Artist (Year)                             │  <- centered caption
└──────────────────────────────────────────────────────┘
```

**Visual rules:**

- **Full-bleed painting** (`ImageOps.fit`): covers the whole display, preserving proportions with centered crop (LANCZOS)
- **Caption** (optional, if metadata is available): solid `BG` rectangle, top border `1px INK_MUTED`, text `"Title, Artist (Year)"` in `--font-body` Italic, `--text-xs`, `--color-ink`
  - Horizontally centered; positioned `30px` from the bottom display edge
  - Maximum width 80% of display (`MAX_W = W x 0.80`); truncated with `…` if it exceeds
  - Padding: `16px` horizontal, `7px` vertical
- **No other UI elements**: no banner, calendar, footer, or status indicators are shown
- **On e-ink**: the painting goes through `EinkRenderer.process()` - palette quantization + dithering (`eink_dither: true` recommended)

**Return to planner:** **A** button (e-ink) / `A` HDMI -> planner resumes immediately.

---

## Shutdown Screen

**Goal:** leave an aesthetically pleasing image on the e-ink panel (instead of a blank white screen) before Raspberry Pi shutdown.

**Activation:** **D** button (Inky Impression) / `D` key (pygame HDMI).

**Behavior:** identical to the artwork screen - same query, same full-bleed layout with caption. The panel keeps the image after shutdown (e-ink is bistable).

---

```css
:root {
  /* Typography */
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

  /* Colors (day mode) */
  --color-bg:          #FFFFFF;
  --color-bg-alt:      #EEECE6;
  --color-ink:         #111111;
  --color-ink-muted:   #666666;
  --color-ink-faint:   #AAAAAA;
  --color-accent:      #1A1A1A;
  --color-holiday:     #444444;
  --color-rule:        #CCCCAA;
  --color-rule-strong: #333333;

  /* Structure */
  --height-banner-main:   90px;      /* Upper band: date and current weather */
  --height-banner-hourly: 127px;     /* Lower band: bi-hourly forecast */
  --height-banner:        217px;     /* Total weather banner (portrait) / weather section (landscape) */
  --height-calendar:      560px;     /* Monthly calendar: 4 event lines per cell (portrait only) */
  --height-footer:        54px;
  --col-left-ratio:       50%;       /* Left column width in landscape */
  --border-radius:        0;         /* Never round corners */
  --shadow:               none;      /* Never add shadows */
}
```

---

## Target Displays

Pixel-specific values for supported displays:

| Display | Resolution | Default layout | Left column | Right column | Appointment list |
|---|---|---|---|---|---|
| HDMI 7" | 1024x600 | `landscape` | 512px | 512px | 546px height |
| Inky Impression 13.3" | 1600x1200 | `landscape` | 800px | 800px | 1146px height |
| HDMI portrait (rotated) | 600x1024 | `portrait` | - | - | 193px height |
| E-ink portrait (rotated) | 1200x1600 | `portrait` | - | - | 769px height |

Portrait calculations: list = `height - 217px - 560px - 54px`.  
Landscape calculations: list height = `height - 54px`; left column = `width x 0.50`.

---

## Layout Configuration

The layout is selected via the `display.layout` field in the YAML configuration file:

```yaml
display:
  layout: "landscape"   # "landscape" | "portrait"
  eink_model: "inky_impression_13"   # see supported models table
  eink_palette: "spectra6"           # "bw" | "bwr" | "4gray" | "spectra6"
  eink_dither: true                  # Floyd-Steinberg dithering
  eink_saturation: 0.5               # color saturation for spectra6 palette (0.0-1.0)
```

The HTML template applies a corresponding CSS class to the `<body>` tag:

```html
<body class="layout-landscape">
<!-- or -->
<body class="layout-portrait">
```

The two classes select their respective CSS blocks (column flexbox for landscape, vertical stack for portrait). `PillowEinkRenderer` reads `config.display.layout` to select the corresponding rendering method.
