#!/usr/bin/env python3
"""Genera app/assets/icons/icons.json dal catalogo icone del progetto.

Legge tutti i nomi di icone Tabler usati (emoji + meteo) da
app/renderer/icon_catalog.py e scrive una lista JSON ordinata.

Utilizzo:
    python scripts/extract_icons.py
    python scripts/extract_icons.py --output path/to/output.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Aggiunge la root del repository al sys.path per permettere l'import di app.*
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from app.renderer.icon_catalog import ALL_ICONS  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Estrai i nomi delle icone usate nel progetto in icons.json")
    parser.add_argument(
        "--output",
        default=str(_REPO_ROOT / "app" / "assets" / "icons" / "icons.json"),
        help="Percorso del file JSON di output (default: app/assets/icons/icons.json)",
    )
    args = parser.parse_args()

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {"icons": sorted(ALL_ICONS)}
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")

    print(f"Scritte {len(ALL_ICONS)} icone in {output_path.relative_to(_REPO_ROOT)}")


if __name__ == "__main__":
    main()
