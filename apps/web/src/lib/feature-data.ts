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
 * `_slugs.json` index (regenerated via `scripts/extract-static-data.ts`).
 * This loader fetches them via fs at build time and the Cloudflare ASSETS
 * binding at runtime — same trick as `loadFeatureTranslations`.
 */

async function readFromFs<T>(relPath: string): Promise<T | null> {
  try {
    const fs = await import("node:fs/promises");
    const path = await import("node:path");
    const filePath = path.join(process.cwd(), "public", relPath);
    const text = await fs.readFile(filePath, "utf8");
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

async function readFromAssets<T>(relPath: string): Promise<T | null> {
  try {
    const { getCloudflareContext } = await import("@opennextjs/cloudflare");
    const ctx = getCloudflareContext({ async: false });
    const env = ctx?.env as { ASSETS?: { fetch: typeof fetch } } | undefined;
    if (!env?.ASSETS) return null;
    const url = new URL(relPath, "https://assets.local");
    const res = await env.ASSETS.fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function readFromHttp<T>(relPath: string): Promise<T | null> {
  try {
    const base =
      process.env.NEXT_PUBLIC_SITE_URL ??
      process.env.NEXT_PUBLIC_BASE_URL ??
      "http://localhost:3000";
    const res = await fetch(new URL(relPath, base));
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

async function loadJson<T>(relPath: string): Promise<T | null> {
  return (
    (await readFromFs<T>(relPath)) ??
    (await readFromAssets<T>(relPath)) ??
    (await readFromHttp<T>(relPath))
  );
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
  const list = (await loadJson<string[]>(`/data/${feature}/_slugs.json`)) ?? [];
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
  const data = await loadJson<T>(`/data/${feature}/${slug}.json`);
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
