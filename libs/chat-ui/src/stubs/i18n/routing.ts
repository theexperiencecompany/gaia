/**
 * Stub for chat-ui — real impl in apps/web. Replace at integration time.
 *
 * Source uses next-intl's defineRouting; this stub provides a shape-compatible
 * config object without pulling next-intl into the chat-ui build.
 */
import { defaultLocale, locales } from "./config";

export const routing = {
  locales,
  defaultLocale,
  localePrefix: "as-needed" as const,
};
