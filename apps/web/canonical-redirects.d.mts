/**
 * Types for `canonical-redirects.mjs`. The plain-js lives next to
 * `next.config.mjs`, which cannot import TS modules.
 */

/** [victim path, canonical winner path], both root-relative, locale-unprefixed. */
export type CanonicalRedirectPair = readonly [from: string, to: string];

export const CANONICAL_REDIRECT_PAIRS: readonly CanonicalRedirectPair[];

export function expandCanonicalRedirects(
  pairs?: readonly CanonicalRedirectPair[],
): Array<{ source: string; destination: string; permanent: true }>;

/** [removed page path, the page that replaced it], root-relative, locale-unprefixed. */
export const RETIRED_PAGE_PAIRS: readonly CanonicalRedirectPair[];
