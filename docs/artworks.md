# Artwork — Art Institute of Chicago

Family Planner integra la visualizzazione di dipinti di dominio pubblico attraverso l'API pubblica dell'**Art Institute of Chicago (ARTIC)**, senza necessità di registrazione o API key.

---

## Razionale della Scelta

### Perché una funzionalità artwork?

Il display mostra i dati del calendario di famiglia in un luogo condiviso (cucina, ingresso, studio). In presenza di ospiti o quando il dispositivo è incustodito, è desiderabile poter nascondere rapidamente gli appuntamenti privati senza spegnere il display. La schermata artwork risolve questo caso d'uso: sostituisce il planner con un contenuto visivamente gradevole e privo di informazioni sensibili.

Sulla modalità e-ink, dove ogni refresh richiede 15–30 secondi, l'artwork serve anche come **schermata di spegnimento**: il pannello e-ink è bistabile e mantiene l'ultima immagine visualizzata indefinitamente, anche senza alimentazione. Un dipinto di qualità è esteticamente più gradevole di uno schermo bianco o di dati calendario statici.

### Perché l'Art Institute of Chicago?

| Criterio | Valutazione |
|---|---|
| **Nessuna API key** | L'API ARTIC è completamente pubblica, senza registrazione né quota |
| **Dominio pubblico** | La collezione è filtrabile per `is_public_domain: true` — nessun problema di copyright |
| **IIIF** | Le immagini ad alta risoluzione sono servite via IIIF standard — richiesta diretta per larghezza, altezza calcolata server-side |
| **Varietà** | La collezione conta oltre 100.000 opere indicizzate, con metadati strutturati (titolo, artista, anno) |
| **Qualità** | Digitalizzazioni ad alta risoluzione, adatte sia a display HDMI sia a pannelli e-ink |
| **Nessun costo** | Gratuita per uso personale / non commerciale |

Altre API considerate e scartate:

| API | Motivo scarto |
|---|---|
| Wikimedia Commons | Catalog eterogeneo, qualità variabile, più complessa da filtrare per tipo/dimensione |
| Metropolitan Museum of Art | API pubblica (simile), ma IIIF non standard — download meno ottimizzato per dimensioni specifiche |
| Unsplash / Pexels | Richiedono API key; contenuto fotografico, non pittorico |
| NASA APOD | Tematica troppo specifica; non sempre adatta al contesto domestico |

---

## API Utilizzate

### 1. Search — `POST /api/v1/artworks/search`

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

- `q`: testo libero configurabile via `artwork.query` nel file di configurazione (default: `"landscape painting"`)
- `is_public_domain: true`: filtra solo opere di dominio pubblico
- `exists image_id`: esclude le opere senza immagine disponibile
- `limit: 100`: recupera 100 candidati per massimizzare la varietà; la selezione finale è casuale

**Risposta (schema rilevante):**

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

`artist_display` può essere multiriga (nome + nazionalità/date); il renderer usa solo la prima riga.

### 2. IIIF Image — `GET /{image_id}/full/{width},/0/default.jpg`

```
GET https://www.artic.edu/iiif/2/{image_id}/full/{width},/0/default.jpg
```

- `{image_id}`: UUID dell'immagine dalla risposta search
- `{width}`: larghezza in pixel del display (`display.width`) — l'altezza è calcolata server-side preservando le proporzioni originali
- Il server IIIF di ARTIC è protetto da CloudFront; richiede header `User-Agent` e `Referer` browser-like per evitare risposte 403

---

## Implementazione

### Modulo: `app/renderer/pillow_eink_renderer.py`

**Costanti:**

```python
_ARTIC_SEARCH_URL = "https://api.artic.edu/api/v1/artworks/search"
_ARTIC_IIIF_TPL   = "https://www.artic.edu/iiif/2/{image_id}/full/{width},/0/default.jpg"
_ARTWORK_QUERY_DEFAULT = "landscape painting"
```

**Funzione `_fetch_artwork(width, height, query)`:**

1. Invia la POST search con la query configurata
2. Filtra i risultati per presenza di `image_id`
3. Esegue un `random.shuffle()` sulla lista per garantire varietà
4. Prova i primi `_MAX_ATTEMPTS = 5` candidati in sequenza — alcuni URL IIIF restituiscono 403 anche per opere marcate public domain (problemi CDN transitori)
5. Per ogni candidato valido:
   - Scarica l'immagine IIIF
   - Applica `ImageOps.fit(img, (width, height), LANCZOS)` — crop centrato per coprire esattamente il display
   - Costruisce la didascalia: `"Titolo, Artista (Anno)"`
6. In caso di errore totale (tutti i tentativi falliti o eccezione di rete): ritorna `None`

**Metodo `PillowEinkRenderer.render_artwork()`:**

```python
def render_artwork(self) -> Image.Image:
    palette = get_palette()
    W, H = self._size
    img = Image.new("RGB", (W, H), palette["BG"])   # fallback sfondo bianco
    result = _fetch_artwork(W, H, self._artwork_query)
    if result is not None:
        artwork_img, caption = result
        img.paste(artwork_img)
        if caption:
            self._draw_artwork_caption(img, caption, palette)
    return img
```

**Metodo `_draw_artwork_caption()`:**

- Rettangolo solido `BG` con bordo superiore `1px INK_MUTED`
- Testo in IBM Plex Sans Italic (`_font_desc_italic`), `TEXT_XS`
- Centrato orizzontalmente, a `30px` dal bordo inferiore
- Troncato con `…` se supera `MAX_W = W × 0.80`

### Header HTTP anti-403

CloudFront/Fastly sul CDN di ARTIC blocca i client con User-Agent non browser. La sessione `requests` usa:

```python
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 ...",
    "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.artic.edu/",
}
```

---

## Configurazione

```yaml
artwork:
  query: "landscape painting"   # stringa di ricerca — qualsiasi termine valido per ARTIC
```

Esempi di query:

| Query | Tipo di opere |
|---|---|
| `landscape painting` | Paesaggi pittorici (default) |
| `impressionism` | Opere impressioniste |
| `japanese woodblock` | Stampe xilografiche giapponesi |
| `portrait oil` | Ritratti ad olio |
| `abstract` | Arte astratta |
| `still life` | Nature morte |

La query viene passata direttamente al motore full-text Elasticsearch di ARTIC (campo `q`) — si possono usare termini singoli, frasi o operatori booleani supportati da ARTIC.

---

## Gestione degli Errori

| Scenario | Comportamento |
|---|---|
| Nessuna connessione di rete | `_fetch_artwork` ritorna `None` → sfondo `BG` uniforme |
| Tutti i tentativi IIIF restituiscono 403 | `_fetch_artwork` ritorna `None` → sfondo `BG` uniforme |
| Nessun risultato per la query | Warning log → sfondo `BG` uniforme |
| Errore parse JSON | Eccezione catturata → sfondo `BG` uniforme |
| Timeout (8s search / 15s image) | `requests.exceptions` → sfondo `BG` uniforme |

In tutti i casi di errore, `render_artwork()` ritorna comunque un `PIL.Image` valido (sfondo `BG`). Il processo non viene mai interrotto.

---

## Privacy e Sicurezza

- **Nessuna API key**: nessuna credenziale da gestire o proteggere
- **Solo rete in uscita**: nessun dato locale viene trasmesso all'API ARTIC (la query è configurata dall'utente)
- **Contenuto di dominio pubblico**: il filtro `is_public_domain: true` garantisce che le opere non siano soggette a restrizioni di copyright
- **Timeout espliciti**: `requests` usa `timeout=8s` per la search e `timeout=15s` per il download immagine — nessun blocco indefinito del thread
