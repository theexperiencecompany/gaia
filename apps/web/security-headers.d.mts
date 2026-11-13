/**
 * Types for `security-headers.mjs`. The plain-js lives next to
 * `next.config.mjs`, which cannot import TS modules.
 */

export type SecurityHeader = { key: string; value: string };

export const SANDBOX_PROXY_PATH: string;

export const NEXT_SECURITY_HEADER_RULES: ReadonlyArray<{
  source: string;
  headers: SecurityHeader[];
}>;

export function renderStaticHeaders(cacheRules: string): string;
