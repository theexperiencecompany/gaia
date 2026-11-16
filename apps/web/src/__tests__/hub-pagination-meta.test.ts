/**
 * A translated hub's later pages are directory pages of their own: each
 * canonicals to itself and has a title and description page 1 does not share.
 */
import type * as NextIntlServer from "next-intl/server";
import { describe, expect, it, vi } from "vitest";

import { automateHubMetadata } from "@/app/[locale]/(landing)/automate/metadata";
import { comparisonsHubMetadata } from "@/app/[locale]/(landing)/compare/metadata";
import { glossaryHubMetadata } from "@/app/[locale]/(landing)/learn/metadata";
import { locales } from "@/i18n/config";
import { siteConfig } from "@/lib/seo";

vi.mock("next-intl/server", async (importOriginal) =>
  (await import("./helpers/nextIntlServer")).mockNextIntlServer(
    importOriginal<typeof NextIntlServer>,
  ),
);

const HUBS = [
  { path: "/learn", metadata: glossaryHubMetadata },
  { path: "/automate", metadata: automateHubMetadata },
  { path: "/compare", metadata: comparisonsHubMetadata },
];

describe("paginated hub metadata", () => {
  it.each(HUBS)(
    "$path/page/2 canonicals to itself with its own title and description in every locale",
    async ({ path, metadata }) => {
      for (const locale of locales) {
        const first = await metadata(locale);
        const second = await metadata(locale, 2, 4);
        const prefix = locale === "en" ? "" : `/${locale}`;

        expect(String(second.alternates?.canonical)).toBe(
          `${siteConfig.url}${prefix}${path}/page/2`,
        );
        expect(second.title).not.toEqual(first.title);
        expect(second.description).not.toEqual(first.description);
        expect(String(second.title)).toContain("2");
      }
    },
  );
});
