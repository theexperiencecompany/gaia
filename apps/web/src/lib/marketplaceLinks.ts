import { getServerApiBaseUrl } from "./serverApiBaseUrl";

/**
 * Resolve a direct marketplace detail path for a tool slug, verifying the
 * page exists so SEO cross-links never point at a 404. Returns null when
 * the slug is unknown or the backend is unreachable; callers fall back to
 * a search link or omit the CTA.
 */
export async function resolveMarketplacePath(
  toolSlug: string,
): Promise<string | null> {
  const baseUrl = getServerApiBaseUrl();
  if (!baseUrl || !toolSlug) return null;

  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    const response = await fetch(
      `${baseUrl}/integrations/public/${encodeURIComponent(toolSlug)}`,
      { next: { revalidate: 3600 }, signal: controller.signal },
    );

    clearTimeout(timeoutId);

    if (!response.ok) return null;
    const data = (await response.json()) as { slug?: string };
    return data.slug ? `/marketplace/${data.slug}` : null;
  } catch {
    return null;
  }
}
