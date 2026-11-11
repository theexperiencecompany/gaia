/**
 * Types for `vanity-redirects.mjs`. The plain-js lives next to
 * `next.config.mjs`, which cannot import TS modules.
 */

/** [vanity path, destination], the path root-relative and locale-unprefixed. */
export type VanityRedirectPair = readonly [from: string, to: string];

export const VANITY_REDIRECT_PAIRS: readonly VanityRedirectPair[];

export function vanityTarget(path: string): string;

export function vanityRedirects(): Array<{
  source: string;
  destination: string;
  permanent: true;
}>;
