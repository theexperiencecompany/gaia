// @vitest-environment jsdom
/** A translated /automate combo page's compare cards read in the page's language, not English. */
import { createTranslator, NextIntlClientProvider } from "next-intl";
import type { ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { ComboCompareLinks } from "@/app/[locale]/(landing)/automate/[combo]/ComboLinkSections";
import type { IntegrationCombo } from "@/features/integrations/data/combosData";
import { defaultLocale, locales } from "@/i18n/config";
import { readMessages } from "./helpers/nextIntlServer";

vi.mock("@/i18n/navigation", () => ({
  Link: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

const COMBO = { toolA: "Notion", toolB: "Slack" } as IntegrationCombo;
const ENGLISH_COPY = ["Compare the tools", "full comparison", "head-to-head"];

function renderCompareLinks(locale: string): string {
  const messages = readMessages(locale);
  return renderToStaticMarkup(
    <NextIntlClientProvider locale={locale} messages={messages}>
      <ComboCompareLinks
        data={COMBO}
        toolACompareHref="/compare/notion"
        toolBCompareHref="/compare/slack"
        t={createTranslator({ locale, messages })}
      />
    </NextIntlClientProvider>,
  );
}

describe("combo compare cards", () => {
  it.each(locales.filter((locale) => locale !== defaultLocale))(
    "%s compare cards carry no English copy",
    (locale) => {
      const html = renderCompareLinks(locale);
      expect(html).toContain("Notion");
      expect(html).toContain("Slack");
      for (const copy of ENGLISH_COPY) expect(html).not.toContain(copy);
    },
  );

  it("names both tools in the English cards", () => {
    const html = renderCompareLinks(defaultLocale);
    expect(html).toContain("GAIA vs Notion: full comparison");
    expect(html).toContain("See how GAIA compares to Slack head-to-head.");
  });
});
