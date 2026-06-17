"""Artwork screensaver — random public-domain painting + caption.

The painting is photographic and benefits from dithering, so the renderer marks
its whole region as ditherable; the caption box is then *unmarked* so its text
stays crisp.
"""
from __future__ import annotations

import io
import logging
import random
from typing import TYPE_CHECKING

import numpy as np
from PIL import Image, ImageEnhance, ImageOps

if TYPE_CHECKING:
    from app.renderer.components.context import RenderContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Art Institute of Chicago public API (no key required)
# ---------------------------------------------------------------------------

_ARTIC_SEARCH_URL: str = "https://api.artic.edu/api/v1/artworks/search"
_ARTIC_IIIF_TPL: str = (
    "https://www.artic.edu/iiif/2/{image_id}/full/{width},/0/default.jpg"
)

ARTWORK_QUERY_DEFAULT: str = "landscape painting"

Rect = tuple[int, int, int, int]

# ---------------------------------------------------------------------------
# E-ink colour enhancement
# ---------------------------------------------------------------------------

# Default enhancement values tuned for the Spectra 6 panel.
# The panel absorbs brightness and desaturates colours compared to a monitor;
# these defaults compensate for that effect before dithering.
_DEFAULT_GAMMA: float = 0.50       # < 1.0 → schiarisce; prova 0.45–0.60
_DEFAULT_SATURATION: float = 1.45  # boost colori prima dello snap alla palette
_DEFAULT_BRIGHTNESS: float = 1.15  # leggero boost finale di luminosità


def enhance_for_eink(
    image: Image.Image,
    *,
    gamma: float = _DEFAULT_GAMMA,
    saturation: float = _DEFAULT_SATURATION,
    brightness: float = _DEFAULT_BRIGHTNESS,
) -> Image.Image:
    """Enhance a photographic ``Image`` to look natural on an e-ink Spectra 6 panel.

    The Spectra 6 display renders colours significantly darker and more muted
    than a monitor or print.  This pipeline compensates by:

    1. **Saturation boost** — vivid hues survive the palette snap better.
    2. **Gamma correction** — raises mid-tones without blowing out highlights
       (``gamma < 1.0`` brightens; ``gamma > 1.0`` darkens).
    3. **Brightness nudge** — a final linear lift to recover any remaining
       darkness after quantisation.

    The function is a no-op when the display is not e-ink (``gamma=1``,
    ``saturation=1``, ``brightness=1``).

    Args:
        image:      RGB ``PIL.Image`` to enhance (not modified in place).
        gamma:      Exponent applied per-channel.  Default ``0.50``.
        saturation: Colour saturation multiplier.  Default ``1.45``.
        brightness: Linear brightness multiplier applied last.  Default ``1.15``.

    Returns:
        A new RGB ``PIL.Image`` with the corrections applied.
    """
    img = image.convert("RGB")

    # 1. Saturation — do this first, before gamma shifts luminance.
    if saturation != 1.0:
        img = ImageEnhance.Color(img).enhance(saturation)

    # 2. Gamma correction via numpy (fast, avoids LUT rounding on float ops).
    if gamma != 1.0:
        arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = np.power(arr, gamma)
        img = Image.fromarray((arr * 255.0).clip(0, 255).astype(np.uint8), "RGB")

    # 3. Final brightness nudge.
    if brightness != 1.0:
        img = ImageEnhance.Brightness(img).enhance(brightness)

    return img


def fetch_artwork(
    width: int,
    height: int,
    query: str = ARTWORK_QUERY_DEFAULT,
    *,
    eink_enhance: bool = False,
    gamma: float = _DEFAULT_GAMMA,
    saturation: float = _DEFAULT_SATURATION,
    brightness: float = _DEFAULT_BRIGHTNESS,
) -> "tuple[Image.Image, str] | None":
    """Fetch a random public-domain artwork matching *query* and crop-fill it.

    Returns a ``(image, caption)`` tuple, or ``None`` on any network/parse error
    (the caller falls back to a plain background).

    Args:
        width:         Target canvas width in pixels.
        height:        Target canvas height in pixels.
        query:         Free-text search query for the ARTIC API.
        eink_enhance:  When ``True``, applies :func:`enhance_for_eink` before
                       returning.  Pass ``True`` for e-ink targets, ``False``
                       for HDMI/browser preview.
        gamma:         Forwarded to :func:`enhance_for_eink`.
        saturation:    Forwarded to :func:`enhance_for_eink`.
        brightness:    Forwarded to :func:`enhance_for_eink`.
    """
    _MAX_ATTEMPTS = 5
    _BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux aarch64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.artic.edu/",
    }
    try:
        import requests

        session = requests.Session()
        session.headers.update(_BROWSER_HEADERS)

        resp = session.post(
            _ARTIC_SEARCH_URL,
            json={
                "q": query,
                "query": {
                    "bool": {
                        "must": [
                            {"term": {"is_public_domain": True}},
                            {"exists": {"field": "image_id"}},
                        ]
                    }
                },
                "fields": ["id", "image_id", "title", "artist_display", "date_display"],
                "limit": 100,
            },
            timeout=8,
        )
        resp.raise_for_status()
        artworks = [a for a in resp.json().get("data", []) if a.get("image_id")]
        if not artworks:
            logger.warning("fetch_artwork: nessun artwork trovato in risposta ARTIC.")
            return None

        random.shuffle(artworks)
        for attempt, artwork in enumerate(artworks[:_MAX_ATTEMPTS], start=1):
            img_url = _ARTIC_IIIF_TPL.format(image_id=artwork["image_id"], width=width)
            try:
                img_resp = session.get(img_url, timeout=15)
                img_resp.raise_for_status()
            except requests.exceptions.HTTPError as exc:
                logger.warning(
                    "fetch_artwork: tentativo %d/%d fallito (%s) — provo il prossimo.",
                    attempt, _MAX_ATTEMPTS, exc,
                )
                continue
            img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
            cover = ImageOps.fit(img, (width, height), Image.Resampling.LANCZOS)
            if eink_enhance:
                cover = enhance_for_eink(
                    cover,
                    gamma=gamma,
                    saturation=saturation,
                    brightness=brightness,
                )

            title = (artwork.get("title") or "").strip()
            artist = (artwork.get("artist_display") or "").split("\n")[0].strip()
            year = (artwork.get("date_display") or "").strip()
            parts = [p for p in [title, artist] if p]
            caption = ", ".join(parts)
            if year:
                caption = f"{caption} ({year})" if caption else f"({year})"

            logger.info("fetch_artwork: «%s» di %s", title or "?", artist or "?")
            return cover, caption

        logger.warning("fetch_artwork: tutti i %d tentativi falliti — uso sfondo BG.", _MAX_ATTEMPTS)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("fetch_artwork: impossibile scaricare artwork — uso sfondo BG.")
        return None


def draw_artwork_caption(ctx: "RenderContext", caption: str) -> Rect:
    """Draw a caption box centred at the bottom edge; return its bounding box."""
    palette = ctx.palette
    W, H = ctx.size
    draw = ctx.draw
    font = ctx.fonts.desc_italic

    PAD_X = 16
    PAD_Y = 7
    MARGIN_BOTTOM = 30
    MAX_W = int(W * 0.80)

    # Truncate with ellipsis if the text is too wide.
    text = caption
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    if text_w > MAX_W - PAD_X * 2:
        while text and text_w > MAX_W - PAD_X * 2 - draw.textlength("…", font=font):
            text = text[:-1]
            bbox = draw.textbbox((0, 0), text, font=font)
            text_w = bbox[2] - bbox[0]
        text = text.rstrip(", ") + "…"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]

    text_h = bbox[3] - bbox[1]
    box_w = text_w + PAD_X * 2
    box_h = text_h + PAD_Y * 2

    x0 = (W - box_w) // 2
    y0 = H - box_h - MARGIN_BOTTOM

    # Solid background box, top border line, caption text.
    ctx.rectangle([x0, y0, x0 + box_w, y0 + box_h], fill=palette["BG"])
    ctx.line([x0, y0, x0 + box_w, y0], fill=palette["INK_MUTED"], width=1)
    ctx.text((x0 + PAD_X, y0 + PAD_Y), text, font=font, fill=palette["INK"])

    return (x0, y0, x0 + box_w, y0 + box_h)
