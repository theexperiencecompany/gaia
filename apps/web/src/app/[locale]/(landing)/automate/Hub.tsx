import { Button } from "@heroui/button";
import type { Metadata } from "next";
import Image from "next/image";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubPagination } from "@/components/seo/HubPagination";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import { getTranslatedCombos } from "@/features/integrations/data/getTranslatedCombo";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import {
  HUB_PAGE_SIZE,
  hubPageCount,
  hubPageHref,
  hubPageSlice,
} from "@/lib/hubPagination";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

export async function automateHubMetadata(locale: string): Promise<Metadata> {
  const t = await getTranslations({ locale, namespace: "automate" });

  return generateLocalizedPageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
    path: "/automate",
    keywords: [
      "automate tools together",
      "tool automation combos",
      "Gmail Slack automation",
      "Notion Todoist automation",
      "GitHub Linear automation",
      "AI workflow automation",
      "connect two apps AI",
      "productivity tool automation",
    ],
    locale,
  });
}

const TOOL_DOMAINS: Record<string, string> = {
  airtable: "airtable.com",
  asana: "asana.com",
  clickup: "clickup.com",
  discord: "discord.com",
  figma: "figma.com",
  github: "github.com",
  gmail: "gmail.com",
  "google-calendar": "calendar.google.com",
  "google-drive": "drive.google.com",
  hubspot: "hubspot.com",
  jira: "atlassian.com",
  linear: "linear.app",
  loom: "loom.com",
  "microsoft-teams": "teams.microsoft.com",
  notion: "notion.so",
  salesforce: "salesforce.com",
  slack: "slack.com",
  stripe: "stripe.com",
  teams: "teams.microsoft.com",
  todoist: "todoist.com",
  trello: "trello.com",
  zoom: "zoom.us",
};

function ToolFavicon({
  slug,
  name,
  rotate,
  zIndex,
}: {
  readonly slug: string;
  readonly name: string;
  readonly rotate: string;
  readonly zIndex: number;
}) {
  const domain = TOOL_DOMAINS[slug];
  if (!domain) return null;
  return (
    <div
      className="relative flex h-8 w-8 shrink-0 items-center justify-center overflow-hidden rounded-md"
      style={{ rotate, zIndex }}
    >
      <Image
        src={`https://www.google.com/s2/favicons?domain=${domain}&sz=128`}
        alt={name}
        width={32}
        height={32}
        unoptimized
      />
    </div>
  );
}

interface AutomateHubProps {
  readonly locale: string;
  readonly page: number;
}

export async function AutomateHub({ locale, page }: AutomateHubProps) {
  setRequestLocale(locale);
  const [t, tCommon, allCombos] = await Promise.all([
    getTranslations({ locale, namespace: "automate" }),
    getTranslations({ locale, namespace: "common" }),
    getTranslatedCombos(locale),
  ]);
  // getTranslatedCombos is _slugs-driven: consolidated victims (which 308 via
  // canonical-redirects.mjs) are already excluded — no marker filter needed.

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    `${siteConfig.url}/automate`,
    [
      { name: "Home", url: siteConfig.url },
      { name: t("breadcrumb"), url: `${siteConfig.url}/automate` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/automate` },
  ]);

  const itemListSchema = generateItemListSchema(
    allCombos.slice(0, 50).map((c) => ({
      name: `${t("automate_with_gaia", { toolA: c.toolA, toolB: c.toolB })}`,
      url: `${siteConfig.url}/automate/${c.slug}`,
    })),
  );

  // Cards are rendered grouped by first letter of toolA, so page through that
  // order rather than raw data order: each page is a contiguous chunk of the
  // list the hub has always shown, and a letter is split at most once.
  const byLetter: Record<string, typeof allCombos> = {};
  for (const combo of allCombos) {
    const letter = combo.toolA[0].toUpperCase();
    if (!byLetter[letter]) byLetter[letter] = [];
    byLetter[letter].push(combo);
  }
  const letters = Object.keys(byLetter).sort((a, b) => a.localeCompare(b));
  const orderedCombos = letters.flatMap((letter) => byLetter[letter]);

  // Only the current page's combos are serialized: the full list is paged so
  // neither the HTML nor the RSC flight payload carries every card.
  const totalPages = hubPageCount(orderedCombos.length);
  const currentPage = Math.min(Math.max(page, 1), totalPages);
  const pageCombos = hubPageSlice(orderedCombos, currentPage);

  const letterPages = new Map<string, number>();
  for (const [index, combo] of orderedCombos.entries()) {
    const letter = combo.toolA[0].toUpperCase();
    if (!letterPages.has(letter)) {
      letterPages.set(letter, Math.floor(index / HUB_PAGE_SIZE) + 1);
    }
  }

  const grouped: Record<string, typeof allCombos> = {};
  for (const combo of pageCombos) {
    const letter = combo.toolA[0].toUpperCase();
    if (!grouped[letter]) grouped[letter] = [];
    grouped[letter].push(combo);
  }
  const pageLetters = Object.keys(grouped).sort((a, b) => a.localeCompare(b));

  return (
    <>
      <JsonLd data={[webPageSchema, breadcrumbSchema, itemListSchema]} />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <header className="mb-16 text-center">
          <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
            {t("hub_title")}
          </h1>
          <p className="mx-auto max-w-2xl text-xl text-zinc-400">
            {t("hub_subtitle")}
          </p>
          <p className="mt-3 text-sm text-zinc-500">
            {t("combos_count", { count: allCombos.length })}
          </p>
        </header>

        {/* Letter jump nav */}
        <div className="mb-12 flex flex-wrap gap-2">
          {letters.map((letter) => {
            const targetPage = letterPages.get(letter) ?? 1;
            return (
              <SiteLink
                key={letter}
                href={
                  targetPage === currentPage
                    ? `#letter-${letter}`
                    : `${hubPageHref("/automate", targetPage)}#letter-${letter}`
                }
                className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-800 text-sm font-medium text-zinc-400 transition hover:bg-zinc-700 hover:text-white"
              >
                {letter}
              </SiteLink>
            );
          })}
        </div>

        {/* Grouped combos */}
        {pageLetters.map((letter) => (
          <div key={letter} id={`letter-${letter}`} className="mb-12">
            <h2 className="mb-4 border-b border-zinc-700 pb-2 text-xl font-semibold text-zinc-300">
              {letter}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {grouped[letter].map((combo) => (
                <SiteLink
                  key={combo.slug}
                  href={`/automate/${combo.slug}`}
                  className="group flex flex-col gap-3 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
                >
                  <div className="flex items-center -space-x-2">
                    <ToolFavicon
                      slug={combo.toolASlug}
                      name={combo.toolA}
                      rotate="-9deg"
                      zIndex={1}
                    />
                    <ToolFavicon
                      slug={combo.toolBSlug}
                      name={combo.toolB}
                      rotate="9deg"
                      zIndex={0}
                    />
                  </div>
                  <h3 className="text-base font-medium text-white transition-colors group-hover:text-primary">
                    {combo.toolA} + {combo.toolB}
                  </h3>
                  <p className="line-clamp-2 text-sm leading-relaxed text-zinc-500">
                    {combo.tagline}
                  </p>
                </SiteLink>
              ))}
            </div>
          </div>
        ))}

        <HubPagination
          pathname="/automate"
          page={currentPage}
          totalPages={totalPages}
        />

        {/* CTA */}
        <div className="mt-8 rounded-3xl bg-zinc-800 p-8 text-center">
          <h2 className="mb-3 text-2xl font-semibold text-white">
            {t("dont_see_your_combo")}
          </h2>
          <p className="mb-6 text-zinc-400">{t("dont_see_your_combo_desc")}</p>
          <Button href="/marketplace" as="a" color="primary">
            {tCommon("browse_marketplace")}
          </Button>
        </div>
      </div>

      <FinalSection />
    </>
  );
}
