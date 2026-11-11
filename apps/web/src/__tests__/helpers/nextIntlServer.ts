import { readFileSync } from "node:fs";
import path from "node:path";
import { createTranslator } from "next-intl";
import type * as NextIntlServer from "next-intl/server";

const MESSAGES_DIR = path.join(process.cwd(), "src", "messages");

/** The locale next-intl's request context answers with; a test sets it before each render. */
export const intlRequest = { locale: "en" };

export function readMessages(locale: string): Record<string, unknown> {
  return JSON.parse(
    readFileSync(path.join(MESSAGES_DIR, `${locale}.json`), "utf8"),
  ) as Record<string, unknown>;
}

/** next-intl/server answered from the real message files, for the factory of vi.mock("next-intl/server"). */
export async function mockNextIntlServer(
  importOriginal: () => Promise<typeof NextIntlServer>,
) {
  return {
    ...(await importOriginal()),
    getLocale: async () => intlRequest.locale,
    setRequestLocale: (locale: string) => {
      intlRequest.locale = locale;
    },
    getTranslations: async (
      options?: string | { locale?: string; namespace?: string },
    ) => {
      const { locale = intlRequest.locale, namespace } =
        typeof options === "string" ? { namespace: options } : (options ?? {});
      return createTranslator({
        locale,
        messages: readMessages(locale),
        namespace,
      });
    },
  };
}
