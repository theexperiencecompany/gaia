/**
 * Extract translatable strings from SEO data files into JSON for lingo.dev.
 *
 * Usage:
 *   cd apps/web && npx tsx scripts/extract-i18n.mjs
 *
 * Outputs:
 *   src/features/alternatives/i18n/en.json
 *   src/features/comparisons/i18n/en.json
 *   src/features/glossary/i18n/en.json
 *   src/features/integrations/i18n/en.json
 *   src/features/personas/i18n/en.json
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(__dirname, "..");

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pick(obj, keys) {
  const result = {};
  for (const key of keys) {
    if (key in obj && obj[key] !== undefined) {
      result[key] = obj[key];
    }
  }
  return result;
}

function writeJson(relPath, data) {
  const abs = resolve(webRoot, relPath);
  mkdirSync(dirname(abs), { recursive: true });
  writeFileSync(abs, JSON.stringify(data, null, 2) + "\n", "utf-8");
  return abs;
}

// ---------------------------------------------------------------------------
// Feature definitions
// ---------------------------------------------------------------------------

const features = [
  {
    name: "alternatives",
    modulePath: "../src/features/alternatives/data/alternativesData.ts",
    outputPath: "src/features/alternatives/i18n/en.json",
    exportName: "alternatives",
    isArray: true,
    slugKey: "slug",
    fields: [
      "name",
      "tagline",
      "metaTitle",
      "metaDescription",
      "keywords",
      "painPoints",
      "whyPeopleLook",
      "gaiaReplaces",
      "gaiaAdvantages",
      "migrationSteps",
      "faqs",
      "comparisonRows",
    ],
  },
  {
    name: "comparisons",
    modulePath: "../src/features/comparisons/data/comparisonsData.ts",
    outputPath: "src/features/comparisons/i18n/en.json",
    exportName: "comparisons",
    isArray: false,
    fields: [
      "name",
      "tagline",
      "description",
      "metaTitle",
      "metaDescription",
      "keywords",
      "intro",
      "rows",
      "gaiaAdvantages",
      "competitorAdvantages",
      "verdict",
      "faqs",
    ],
  },
  {
    name: "glossary",
    modulePath: "../src/features/glossary/data/glossaryData.ts",
    outputPath: "src/features/glossary/i18n/en.json",
    exportName: "glossaryTerms",
    isArray: false,
    fields: [
      "term",
      "metaTitle",
      "metaDescription",
      "definition",
      "extendedDescription",
      "keywords",
      "howGaiaUsesIt",
      "faqs",
    ],
  },
  {
    name: "combos",
    modulePath: "../src/features/integrations/data/combosData.ts",
    outputPath: "src/features/integrations/i18n/en.json",
    exportName: "combos",
    isArray: false,
    fields: [
      "toolA",
      "toolB",
      "tagline",
      "metaTitle",
      "metaDescription",
      "keywords",
      "intro",
      "useCases",
      "howItWorks",
      "faqs",
    ],
  },
  {
    name: "personas",
    modulePath: "../src/features/personas/data/personasData.ts",
    outputPath: "src/features/personas/i18n/en.json",
    exportName: "personas",
    isArray: false,
    fields: [
      "title",
      "role",
      "metaTitle",
      "metaDescription",
      "keywords",
      "intro",
      "painPoints",
      "howGaiaHelps",
      "faqs",
    ],
  },
];

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

async function main() {
  const summary = [];

  for (const feature of features) {
    const modulePath = resolve(__dirname, feature.modulePath);
    const mod = await import(modulePath);
    const raw = mod[feature.exportName];

    if (!raw) {
      console.error(
        `  [SKIP] ${feature.name}: export "${feature.exportName}" not found`,
      );
      continue;
    }

    const output = {};

    if (feature.isArray) {
      // alternatives is an array — key by slug
      for (const entry of raw) {
        const slug = entry[feature.slugKey];
        output[slug] = pick(entry, feature.fields);
      }
    } else {
      // Record keyed by slug
      for (const [slug, entry] of Object.entries(raw)) {
        output[slug] = pick(entry, feature.fields);
      }
    }

    const count = Object.keys(output).length;
    const outPath = writeJson(feature.outputPath, output);
    summary.push({ feature: feature.name, entries: count, path: outPath });
  }

  console.log("\n--- extract-i18n summary ---");
  for (const { feature, entries, path } of summary) {
    console.log(`  ${feature}: ${entries} entries -> ${path}`);
  }
  console.log("");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
