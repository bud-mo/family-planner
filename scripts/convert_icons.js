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
 *   node scripts/convert_icons.js --json=app/assets/icons/icons.json  # from JSON catalog
 *   node scripts/convert_icons.js --json=app/assets/icons/icons.json --size=48 --force
 *
 * --json e --name sono mutualmente esclusivi; se entrambi presenti, --json ha priorità.
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

// ---------------------------------------------------------------------------
// Parse CLI arguments
// ---------------------------------------------------------------------------
const argv = process.argv.slice(2);
const force = argv.includes("--force");
const sizeArg = argv.find((a) => a.startsWith("--size="));
const size = sizeArg ? parseInt(sizeArg.split("=")[1], 10) : DEFAULT_SIZE;

const jsonArg = argv.find((a) => a.startsWith("--json="));
const nameArg = argv.find((a) => a.startsWith("--name="));

let filterNames = null;

if (jsonArg) {
  if (nameArg) {
    console.warn("[WARN] --json e --name sono mutualmente esclusivi: --name ignorato.");
  }
  const jsonPath = resolve(REPO_ROOT, jsonArg.split("=")[1]);
  if (!existsSync(jsonPath)) {
    console.error(`ERROR: file JSON non trovato:\n  ${jsonPath}`);
    console.error("Esegui prima: python scripts/extract_icons.py");
    process.exit(1);
  }
  const jsonData = JSON.parse(readFileSync(jsonPath, "utf8"));
  if (!Array.isArray(jsonData.icons)) {
    console.error(`ERROR: il file JSON non contiene una chiave "icons" array.`);
    process.exit(1);
  }
  filterNames = new Set(jsonData.icons.map((n) => String(n).trim()));
  console.log(`Catalogo JSON caricato: ${filterNames.size} icone da ${jsonPath}`);
} else if (nameArg) {
  filterNames = new Set(nameArg.split("=")[1].split(",").map((n) => n.trim()));
}

const OUTPUT_DIR = join(ICONS_BASE_DIR, String(size));

if (!existsSync(SOURCE_DIR)) {
  console.error(`ERROR: source directory not found:\n  ${SOURCE_DIR}`);
  process.exit(1);
}

mkdirSync(OUTPUT_DIR, { recursive: true });

// ---------------------------------------------------------------------------
// Build file list
// ---------------------------------------------------------------------------
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

console.log(`Converting ${svgFiles.length} SVG(s) → ${size}×${size} px PNG`);
console.log(`  Source : ${SOURCE_DIR}`);
console.log(`  Output : ${OUTPUT_DIR}\n`);

// ---------------------------------------------------------------------------
// Convert
// ---------------------------------------------------------------------------
let converted = 0;
let skipped = 0;
let errors = 0;

for (let i = 0; i < svgFiles.length; i++) {
  const svgPath = svgFiles[i];
  const name = basename(svgPath, ".svg");
  const pngPath = join(OUTPUT_DIR, `${name}.png`);

  if (existsSync(pngPath) && !force) {
    skipped++;
    continue;
  }

  try {
    const svgData = readFileSync(svgPath, "utf8");
    const resvg = new Resvg(svgData, {
      fitTo: { mode: "width", value: size },
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

console.log(
  `\nDone — ${converted} converted, ${skipped} skipped, ${errors} errors.`
);
