# Artwork - Art Institute of Chicago

Family Planner includes public-domain artwork display through the **Art Institute of Chicago (ARTIC)** public API, with no registration or API key required.

---

## Why This Feature

### Why add an artwork mode?

The display shows family calendar data in a shared space (kitchen, hallway, office). When guests are present, or when the device is unattended, it is useful to quickly hide private appointments without turning the display off. Artwork mode solves this use case: it replaces the planner with visually pleasing content that contains no sensitive information.

On e-ink devices, where each refresh takes 15-30 seconds, artwork mode also works as a **shutdown screen**: the e-ink panel is bistable and keeps the last displayed image indefinitely, even without power. A high-quality painting is visually better than a white screen or static calendar data.

### Why the Art Institute of Chicago?

| Criterion | Evaluation |
|---|---|
| **No API key** | The ARTIC API is fully public, with no registration or quota |
| **Public domain** | The collection can be filtered with `is_public_domain: true` - no copyright issues |
| **IIIF** | High-resolution images are served through standard IIIF - direct width request, server-side computed height |
| **Variety** | The collection has over 100,000 indexed works, with structured metadata (title, artist, year) |
| **Quality** | High-resolution digitizations, suitable for e-ink panels |
| **No cost** | Free for personal / non-commercial use |

Other APIs considered and rejected:

| API | Reason for rejection |
|---|---|
| Wikimedia Commons | Heterogeneous catalog, variable quality, harder to filter by type/size |
| Metropolitan Museum of Art | Public API (similar), but non-standard IIIF - less optimized downloads for specific dimensions |
| Unsplash / Pexels | Require API key; photographic content, not painting-focused |
| NASA APOD | Topic too specific; not always suitable for a home context |

---

## APIs Used

### 1. Search - `POST /api/v1/artworks/search`

```
POST https://api.artic.edu/api/v1/artworks/search
Content-Type: application/json
```

**Body:**

```json
{
  "q": "landscape painting",
  "query": {
    "bool": {
      "must": [
        { "term": { "is_public_domain": true } },
        { "exists": { "field": "image_id" } }
      ]
    }
  },
  "fields": ["id", "image_id", "title", "artist_display", "date_display"],
  "limit": 100
}
```

- `q`: free-text query configurable through `artwork.query` in the config file (default: `"landscape painting"`)
- `is_public_domain: true`: filters only public-domain works
- `exists image_id`: excludes works without an available image
- `limit: 100`: fetches 100 candidates to maximize variety; final selection is random

**Response (relevant schema):**

```json
{
  "data": [
    {
      "id": 16571,
      "image_id": "1adf2696-8489-499b-cad2-821d7fde4b33",
      "title": "Sunday on La Grande Jatte",
      "artist_display": "Georges Seurat\nFrench, 1859-1891",
      "date_display": "1884-86"
    }
  ]
}
```

`artist_display` can be multi-line (name + nationality/dates); the renderer uses only the first line.

### 2. IIIF Image - `GET /{image_id}/full/{width},/0/default.jpg`

```
GET https://www.artic.edu/iiif/2/{image_id}/full/{width},/0/default.jpg
```

- `{image_id}`: image UUID from the search response
- `{width}`: display width in pixels (`display.width`) - height is computed server-side while preserving original aspect ratio
- ARTIC's IIIF server is protected by CloudFront; it requires browser-like `User-Agent` and `Referer` headers to avoid 403 responses

---

## Implementation

### Module: `app/renderer/pillow_eink_renderer.py`

**Constants:**

```python
_ARTIC_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
_ARTIC_IIIF_TPL   = "https://www.artic.edu/iiif/2/{image_id}/full/{width},/0/default.jpg"
_ARTWORK_QUERY_DEFAULT = "landscape painting"
```

**Function `_fetch_artwork(width, height, query)`:**

1. Sends the search POST request with the configured query
2. Filters results by presence of `image_id`
3. Runs `random.shuffle()` on the list to guarantee variety
4. Tries the first `_MAX_ATTEMPTS = 5` candidates in sequence - some IIIF URLs return 403 even for works marked as public domain (transient CDN issues)
5. For each valid candidate:
   - Downloads the IIIF image
   - Applies `ImageOps.fit(img, (width, height), LANCZOS)` - centered crop to fill the display exactly
   - Builds the caption: `"Title, Artist (Year)"`
6. If everything fails (all attempts fail or a network exception occurs): returns `None`

**Method `PillowEinkRenderer.render_artwork()`:**

```python
def render_artwork(self) -> Image.Image:
    palette = get_palette()
    W, H = self._size
    img = Image.new("RGB", (W, H), palette["BG"])   # white background fallback
    result = _fetch_artwork(W, H, self._artwork_query)
    if result is not None:
        artwork_img, caption = result
        img.paste(artwork_img)
        if caption:
            self._draw_artwork_caption(img, caption, palette)
    return img
```

**Method `_draw_artwork_caption()`:**

- Solid `BG` rectangle with a `1px INK_MUTED` top border
- Text in IBM Plex Sans Italic (`_font_desc_italic`), `TEXT_XS`
- Horizontally centered, `30px` from the bottom edge
- Truncated with `...` if it exceeds `MAX_W = W x 0.80`

### Anti-403 HTTP headers

CloudFront/Fastly on ARTIC's CDN blocks clients with non-browser user agents. The `requests` session uses:

```python
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 ...",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.artic.edu/",
}
```

---

## Configuration

```yaml
artwork:
  query: "landscape painting"   # search string - any ARTIC-valid term
```

Query examples:

| Query | Type of works |
|---|---|
| `landscape painting` | Landscape paintings (default) |
| `impressionism` | Impressionist works |
| `japanese woodblock` | Japanese woodblock prints |
| `portrait oil` | Oil portraits |
| `abstract` | Abstract art |
| `still life` | Still life artworks |

The query is passed directly to ARTIC's Elasticsearch full-text engine (`q` field). You can use single terms, phrases, or boolean operators supported by ARTIC.

---

## Slideshow (auto-advance)

While **artwork mode is active** (either `source: endpoint` or `source: folder`),
a single press of button **C** — its rotation-equivalent **B** when the panel is
mounted upside-down (180°/270°) — **toggles slideshow mode on/off**:

- When **on**, the panel advances to the **next image at a regular interval**: the
  next folder picture in `folder` mode, or a fresh random painting in `endpoint`
  mode — exactly what a manual artwork-button press does, but on a timer.
- The interval is `artwork.slideshow_interval_minutes` (**integer minutes, ≥ 1,
  default 30**), editable from the `/config` web UI. It is read live, so a config
  save changes the cadence of the *next* interval without a restart.
- Pressing C again while the slideshow is on turns it off; the current image stays
  (e-ink is bistable). Leaving artwork mode (planner button) or shutting the device
  down also stops the slideshow.
- Pressing C while **not** in artwork mode is a no-op (logged at INFO).

```yaml
artwork:
  query: "landscape painting"
  slideshow_interval_minutes: 30   # auto-advance cadence; integer minutes, >= 1
```

A slideshow "tick" reuses the same `render_artwork() → process_photo() → push()`
cycle as the manual artwork button — no second render or push route. The timer
lives in `app/display/slideshow.py` (`SlideshowController`), driven from a
dedicated short-lived thread that is started only when an e-ink panel is present.

> **Button C and SPI CS1.** On every model except the 13.3″, button C is BCM16,
> which the Inky driver also uses as SPI CS1. All four GPIO lines are requested
> together; if a board refuses line 16, `InkyButtonHandler` falls back to A/B/D
> only, disabling the slideshow button alone and keeping planner/artwork/shutdown
> working. On `inky_impression_13` button C is BCM25 (no conflict).

---

## Managing artwork from `/config`

The web configuration page (`/config`, Artwork section) lets you manage the
artwork without editing files on the device:

- **Query Test/preview** — next to the query field, a **Test** button performs a
  dry-run: it fetches one image matching the current query and shows it inline
  with its caption, without changing any state. Use it to try queries before
  saving.
- **Picture library** (folder mode) — the *Immagini in `pictures/`* subsection
  lists the files currently in the local artwork folder, each with a thumbnail.
  You can **upload** a new image (`+ Carica immagine`), **rename** a file inline
  (✎ → edit → Salva/Annulla), and **delete** a file (🗑, with confirmation).

Folder edits apply on the **next artwork frame** — no save, no reload. The
renderer rescans the folder on every render, so the config YAML is never
rewritten by a picture operation.

All these endpoints are auth-protected (when Basic Auth is configured) and
confined to the configured folder: file names that contain `..`, path
separators, or that resolve outside the folder (including via symlink) are
rejected, and uploads must be real images. Thumbnails are always PIL-downscaled
— the multi-megabyte originals are never streamed to the browser.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| No network connection | `_fetch_artwork` returns `None` -> uniform `BG` fallback |
| All IIIF attempts return 403 | `_fetch_artwork` returns `None` -> uniform `BG` fallback |
| No results for the query | Warning log -> uniform `BG` fallback |
| JSON parse error | Exception caught -> uniform `BG` fallback |
| Timeout (8s search / 15s image) | `requests.exceptions` -> uniform `BG` fallback |

In all error cases, `render_artwork()` still returns a valid `PIL.Image` (`BG` fallback). The process never crashes.

---

## Privacy and Security

- **No API key**: no credentials to manage or protect
- **Outbound network only**: no local data is transmitted to the ARTIC API (the query is user-configured)
- **Public-domain content**: the `is_public_domain: true` filter ensures works are not subject to copyright restrictions
- **Explicit timeouts**: `requests` uses `timeout=8s` for search and `timeout=15s` for image download - no indefinite thread blocking