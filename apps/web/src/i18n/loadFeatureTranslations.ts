import { defaultLocale } from "./config";

/**
 * Load translated JSON for a feature module.
 *
 * Strategy:
 *   - At build time (Node), read from `public/data/i18n/{feature}/{locale}.json`
 *     directly off disk. No bundling, no HTTP.
 *   - At Cloudflare Workers runtime, fetch through the `ASSETS` binding —
 *     OpenNext for Cloudflare exposes static assets via that binding and
 *     edge-caches them globally.
 *   - Last-resort HTTP fallback (for non-CF non-Node runtimes, e.g. local
 *     `next dev` server-component fetch).
 *
 * Returns empty object for `defaultLocale` (the source strings) or if the file
 * is missing — same contract as the original importer.
 */

const SOURCE_LOCALE_RETURNS_EMPTY = true;

// Lazy-imported helpers so neither code path bloats the other side's bundle.
// The dynamic `import()` keeps `node:fs` out of the Cloudflare worker entirely.

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
    // OpenNext-Cloudflare exposes the static-assets binding here.
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

export async function loadFeatureTranslations<T = Record<string, unknown>>(
  locale: string,
  feature: string,
): Promise<T> {
  if (SOURCE_LOCALE_RETURNS_EMPTY && locale === defaultLocale) return {} as T;

  const relPath = `/data/i18n/${feature}/${locale}.json`;

  // Order: try the cheapest first. fs is free at build time; ASSETS binding
  // is fast at edge; HTTP is the safety net.
  const fromFs = await readFromFs<T>(relPath);
  if (fromFs !== null) return fromFs;

  const fromAssets = await readFromAssets<T>(relPath);
  if (fromAssets !== null) return fromAssets;

  const fromHttp = await readFromHttp<T>(relPath);
  if (fromHttp !== null) return fromHttp;

  console.error(`[i18n] Missing translations for ${feature}/${locale}`);
  return {} as T;
}
