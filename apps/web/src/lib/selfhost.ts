/**
 * Whether this build fronts a self-hosted instance. apps/web/Dockerfile (the
 * self-host image) bakes NEXT_PUBLIC_GAIA_SELFHOST=true; hosted builds never
 * set it. Inlined at build time, so server, middleware and client all agree
 * from first paint without a request, and hosted pages stay static.
 */
export function isSelfhostWeb(): boolean {
  return process.env.NEXT_PUBLIC_GAIA_SELFHOST === "true";
}

/**
 * The params a marketing route prerenders at build: none on a self-host build,
 * which serves no landing pages (its "/" goes into the product), so the image
 * does not carry ~220 MB of SEO pages. Hosted builds load them all.
 */
export async function prerenderedMarketingParams<T>(
  load: () => Promise<T[]> | T[],
): Promise<T[]> {
  return isSelfhostWeb() ? [] : load();
}
