/**
 * Types for `settings-redirects.mjs`. The plain-js lives next to
 * `next.config.mjs`, which cannot import TS modules.
 */

export const DEFAULT_SETTINGS_SECTION: "account";

export function settingsRedirects(): Array<{
  source: string;
  has?: Array<{ type: "query"; key: string; value: string }>;
  destination: string;
  permanent: false;
}>;
