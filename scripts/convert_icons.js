#!/usr/bin/env node
/**
 * Convert Tabler Icons outline SVGs to PNG files.
 *
 * Reads SVGs from  tabler-icons/icons/outline/  and writes PNGs to
 * app/assets/icons/  using @resvg/resvg-js (Rust-based, no system deps).
 *
 * Setup (once):
 *   cd scripts && npm install
 *   python scripts/extract_icons.py   # genera app/assets/icons/icons.json
 *
 * Usage:
 *   node scripts/convert_icons.js                              # skip existing PNGs
 *   node scripts/convert_icons.js --force                     # overwrite all
 *   node scripts/convert_icons.js --size=48                   # custom size (default: 24)
 *   node scripts/convert_icons.js --name=heart,star           # specific icons only
 *   node scripts/convert_icons.js --json=app/assets/icons/icons.json  # from JSON catalog (tutte le dimensioni)
 *
 * Con --json, le dimensioni sono definite nel JSON: --size è ignorato.
 * --json e --name sono mutualmente esclusivi; se entrambi presenti, --name ignorato.
 */

import { Resvg } from "@resvg/resvg-js";
import {
  readFileSync,
  writeFileSync,
  mkdirSync,
  readdirSync,
  existsSync,
} from "fs";
import { join, basename, resolve, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(__dirname, "..");
const SOURCE_DIR = join(REPO_ROOT, "node_modules", "@tabler", "icons", "icons", "outline");
const ICONS_BASE_DIR = join(REPO_ROOT, "app", "assets", "icons");
const DEFAULT_SIZE = 24;

if (!existsSync(SOURCE_DIR)) {
  console.error(`ERROR: source directory not found:\n  ${SOURCE_DIR}`);
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Parse CLI arguments
// ---------------------------------------------------------------------------
const argv = process.argv.slice(2);
const force = argv.includes("--force");
const sizeArg = argv.find((a) => a.startsWith("--size="));
const jsonArg = argv.find((a) => a.startsWith("--json="));
const nameArg = argv.find((a) => a.startsWith("--name="));

// ---------------------------------------------------------------------------
// Helper: convert a batch of SVG paths to PNGs at a given size
// ---------------------------------------------------------------------------
function convertBatch(svgFiles, sizePx, outputDir) {
  mkdirSync(outputDir, { recursive: true });
  console.log(`\nConverting ${svgFiles.length} SVG(s) → ${sizePx}×${sizePx} px PNG`);
  console.log(`  Source : ${SOURCE_DIR}`);
  console.log(`  Output : ${outputDir}`);

  let converted = 0;
  let skipped = 0;
  let errors = 0;

  for (let i = 0; i < svgFiles.length; i++) {
    const svgPath = svgFiles[i];
    const name = basename(svgPath, ".svg");
    const pngPath = join(outputDir, `${name}.png`);

    if (existsSync(pngPath) && !force) {
      skipped++;
      continue;
    }

    try {
      const svgData = readFileSync(svgPath, "utf8");
      const resvg = new Resvg(svgData, {
        fitTo: { mode: "width", value: sizePx },
      });
      const png = resvg.render().asPng();
      writeFileSync(pngPath, png);
      converted++;
    } catch (err) {
      console.error(`  [ERROR] ${name}: ${err.message}`);
      errors++;
    }

    if ((i + 1) % 500 === 0 || i + 1 === svgFiles.length) {
      console.log(`  ${i + 1}/${svgFiles.length} processed …`);
    }
  }

  console.log(`  Done — ${converted} converted, ${skipped} skipped, ${errors} errors.`);
}

// ---------------------------------------------------------------------------
// --json mode: multi-size from JSON catalog
// ---------------------------------------------------------------------------
if (jsonArg) {
  if (nameArg) {
    console.warn("[WARN] --json e --name sono mutualmente esclusivi: --name ignorato.");
  }
  if (sizeArg) {
    console.warn("[WARN] --size è ignorato quando --json è usato: le dimensioni sono definite nel JSON.");
  }

  const jsonPath = resolve(REPO_ROOT, jsonArg.split("=")[1]);
  if (!existsSync(jsonPath)) {
    console.error(`ERROR: file JSON non trovato:\n  ${jsonPath}`);
    console.error("Esegui prima: python scripts/extract_icons.py");
    process.exit(1);
  }

  const jsonData = JSON.parse(readFileSync(jsonPath, "utf8"));
  const sizeKeys = Object.keys(jsonData);
  if (sizeKeys.length === 0) {
    console.error("ERROR: il file JSON è vuoto.");
    process.exit(1);
  }

  console.log(`Catalogo JSON caricato: ${sizeKeys.length} dimensioni da ${jsonPath}`);

  for (const key of sizeKeys) {
    const sizePx = parseInt(key, 10);
    if (isNaN(sizePx)) {
      console.warn(`[WARN] chiave JSON non numerica ignorata: "${key}"`);
      continue;
    }
    const names = jsonData[key];
    if (!Array.isArray(names)) {
      console.warn(`[WARN] valore non array per dimensione ${key}, ignorato.`);
      continue;
    }

    let svgFiles = names.map((n) => join(SOURCE_DIR, `${String(n).trim()}.svg`));
    const missing = svgFiles.filter((p) => !existsSync(p));
    missing.forEach((p) => console.warn(`  [SKIP] not found: ${basename(p)}`));
    svgFiles = svgFiles.filter(existsSync);

    convertBatch(svgFiles, sizePx, join(ICONS_BASE_DIR, key));
  }

  process.exit(0);
}

// ---------------------------------------------------------------------------
// Single-size mode: --name or all SVGs in source directory
// ---------------------------------------------------------------------------
const size = sizeArg ? parseInt(sizeArg.split("=")[1], 10) : DEFAULT_SIZE;
const OUTPUT_DIR = join(ICONS_BASE_DIR, String(size));

let filterNames = null;
if (nameArg) {
  filterNames = new Set(nameArg.split("=")[1].split(",").map((n) => n.trim()));
}

let svgFiles;
if (filterNames) {
  svgFiles = [...filterNames].map((n) => join(SOURCE_DIR, `${n}.svg`));
  const missing = svgFiles.filter((p) => !existsSync(p));
  missing.forEach((p) => console.warn(`  [SKIP] not found: ${basename(p)}`));
  svgFiles = svgFiles.filter(existsSync);
} else {
  svgFiles = readdirSync(SOURCE_DIR)
    .filter((f) => f.endsWith(".svg"))
    .sort()
    .map((f) => join(SOURCE_DIR, f));
}

convertBatch(svgFiles, size, OUTPUT_DIR);
