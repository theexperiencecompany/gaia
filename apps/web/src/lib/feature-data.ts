/**
 * feature-data.ts — runtime + build-time loader for static feature data.
 *
 * Background: large per-feature data files (`alternativesData.ts`,
 * `comparisonsData.ts`, etc.) used to barrel-import 50–200 entries and re-
 * export them as a single object. Any route that called `getAlternative(slug)`
 * pulled the entire dataset into the SSR bundle, blowing up handler.mjs on
 * Cloudflare Workers (3 MB free / 10 MB paid limit).
 *
 * Solution: entries live in `public/data/{feature}/{slug}.json` and a tiny
 * `_slugs.json` index.
 * This loader fetches them via fs at build time and the Cloudflare ASSETS
 * binding at runtime; `loadFeatureTranslations` reads the locale overlays
 * through the same `loadStaticJson`.
 */

import {
  ADVERTISED_PRO_MONTHLY_PRICE,
  PRO_MONTHLY_PRICE_TOKEN,
} from "@/features/pricing/advertisedPrice";

async function readFromFs(relPath: string): Promise<string | null> {
  try {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const filePath = path.join(process.cwd(), "public", relPath);
    return await fs.readFile(filePath, "utf8");
  } catch {
    return null;
  }
}

async function readFromAssets(relPath: string): Promise<string | null> {
  try {
    const { getCloudflareContext } = await import("@opennextjs/cloudflare");
    const ctx = getCloudflareContext({ async: false });
    const env = ctx?.env as { ASSETS?: { fetch: typeof fetch } } | undefined;
    if (!env?.ASSETS) return null;
    const url = new URL(relPath, "https://assets.local");
    const res = await env.ASSETS.fetch(url);
    if (!res.ok) return null;
    return await res.text();
  } catch {
    return null;
  }
}

async function readFromHttp(relPath: string): Promise<string | null> {
  try {
    const base =
      process.env.NEXT_PUBLIC_SITE_URL ??
      process.env.NEXT_PUBLIC_BASE_URL ??
      "http://localhost:3000";
    const res = await fetch(new URL(relPath, base));
    if (!res.ok) return null;
    return await res.text();
  } catch {
    return null;
  }
}

/** Parse static data, writing the advertised price where the copy quotes GAIA's own. */
function parseStaticJson<T>(text: string): T {
  return JSON.parse(
    text.replaceAll(
      PRO_MONTHLY_PRICE_TOKEN,
      String(ADVERTISED_PRO_MONTHLY_PRICE),
    ),
  ) as T;
}

/** Read a `public/` JSON file: fs at build time, ASSETS at the edge, HTTP as the safety net. */
export async function loadStaticJson<T>(relPath: string): Promise<T | null> {
  const text =
    (await readFromFs(relPath)) ??
    (await readFromAssets(relPath)) ??
    (await readFromHttp(relPath));
  return text === null ? null : parseStaticJson<T>(text);
}

const slugsCache = new Map<string, string[]>();
const entryCache = new Map<string, unknown>();

/**
 * Load the slug index for a feature.
 * Cached for the lifetime of the worker / build process.
 */
export async function getFeatureSlugs(feature: string): Promise<string[]> {
  const cached = slugsCache.get(feature);
  if (cached) return cached;
  const list =
    (await loadStaticJson<string[]>(`/data/${feature}/_slugs.json`)) ?? [];
  slugsCache.set(feature, list);
  return list;
}

/**
 * Load a single entry by slug. Returns `undefined` if the file is missing.
 */
export async function getFeatureEntry<T>(
  feature: string,
  slug: string,
): Promise<T | undefined> {
  const key = `${feature}/${slug}`;
  const cached = entryCache.get(key);
  if (cached) return cached as T;
  const data = await loadStaticJson<T>(`/data/${feature}/${slug}.json`);
  if (data) entryCache.set(key, data);
  return data ?? undefined;
}

/**
 * Load every entry for a feature. Use sparingly — this fans out one fetch
 * per slug. For listing pages where this is unavoidable, the result is
 * memoized per process.
 */
export async function getAllFeatureEntries<T>(feature: string): Promise<T[]> {
  const slugs = await getFeatureSlugs(feature);
  const results = await Promise.all(
    slugs.map((slug) => getFeatureEntry<T>(feature, slug)),
  );
  return results.filter((r) => r !== undefined) as T[];
}
