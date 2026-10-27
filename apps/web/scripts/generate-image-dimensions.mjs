#!/usr/bin/env node
/**
 * generate-image-dimensions.mjs: build-time codegen for intrinsic image sizes.
 *
 * `images/dimensions` wants width/height on every <img>, but the dimensions of
 * a local asset are not known at render time unless someone writes them down.
 * This scans public/images and public/brand, reads each file with sharp, and
 * emits src/lib/image-dimensions.generated.json (committed, so builds and
 * tests do not need sharp installed to read it).
 */
import { existsSync, mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, extname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import sharp from "sharp";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const PUBLIC_DIR = join(root, "public");
const OUT_FILE = join(root, "src/lib/image-dimensions.generated.json");
const SOURCE_DIRS = ["images", "brand"];
const EXTENSIONS = new Set([
  ".avif",
  ".gif",
  ".jpeg",
  ".jpg",
  ".png",
  ".svg",
  ".webp",
]);

function walk(dir) {
  const files = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) files.push(...walk(path));
    else if (EXTENSIONS.has(extname(entry.name).toLowerCase())) files.push(path);
  }
  return files;
}

const dimensions = {};
const files = SOURCE_DIRS.flatMap((sourceDir) => {
  const dir = join(PUBLIC_DIR, sourceDir);
  return existsSync(dir) ? walk(dir) : [];
});

await Promise.all(
  files.map(async (file) => {
    const metadata = await sharp(file).metadata();
    if (!metadata.width || !metadata.height) {
      console.warn(`[image-dimensions] skipping ${file}: no intrinsic size`);
      return;
    }

    const key = `/${relative(PUBLIC_DIR, file).split("\\").join("/")}`;
    dimensions[key] = { width: metadata.width, height: metadata.height };
  }),
);

const sorted = Object.fromEntries(
  Object.entries(dimensions).sort(([a], [b]) => a.localeCompare(b)),
);

mkdirSync(dirname(OUT_FILE), { recursive: true });
writeFileSync(OUT_FILE, `${JSON.stringify(sorted, null, 2)}\n`);
console.log(
  `[image-dimensions] wrote ${Object.keys(sorted).length} images -> src/lib/image-dimensions.generated.json`,
);
