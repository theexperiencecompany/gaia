import { Button } from "@heroui/button";
import type { Metadata } from "next";
import Image from "next/image";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubPagination, HubSectionNav } from "@/components/seo/HubPageNav";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { getTranslatedCombos } from "@/features/integrations/data/getTranslatedCombo";
import { comboHubPages } from "@/features/integrations/lib/comboHubPages";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { hubPagePath } from "@/lib/hubPagination";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

const HUB_PATH = "/automate";

const HUB_KEYWORDS = [
  "automate tools together",
  "tool automation combos",
  "Gmail Slack automation",
  "Notion Todoist automation",
  "GitHub Linear automation",
  "AI workflow automation",
  "connect two apps AI",
  "productivity tool automation",
];

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

export async function generateAutomateHubMetadata(
  locale: string,
  page: number,
): Promise<Metadata> {
  const [t, pages] = await Promise.all([
    getTranslations({ locale, namespace: "automate" }),
    getAllCombos().then(comboHubPages),
  ]);
  return generateLocalizedPageMetadata({
    title:
      page === 1
        ? t("hub_meta_title")
        : t("hub_page_meta_title", { page, total: pages.length }),
    description:
      page === 1
        ? t("hub_meta_description")
        : t("hub_page_meta_description", { page, total: pages.length }),
    path: hubPagePath(HUB_PATH, page),
    keywords: HUB_KEYWORDS,
    locale,
  });
}

/** One page of the /automate hub: its apps' combos, the jump links to them, and links to every other page. */
export async function AutomateHubPage({
  locale,
  page,
}: {
  readonly locale: string;
  readonly page: number;
}) {
  setRequestLocale(locale);
  const [t, tCommon, allCombos] = await Promise.all([
    getTranslations({ locale, namespace: "automate" }),
    getTranslations({ locale, namespace: "common" }),
    getTranslatedCombos(locale),
  ]);
  // getTranslatedCombos is _slugs-driven: consolidated victims (which 308 via
  // canonical-redirects.mjs) are already excluded — no marker filter needed.
  const pages = comboHubPages(allCombos);
  const hubPage = pages.find((candidate) => candidate.page === page);
  if (!hubPage) notFound();

  const pageUrl = `${siteConfig.url}${hubPagePath(HUB_PATH, page)}`;
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}${HUB_PATH}` },
    ...(page === 1
      ? []
      : [{ name: tCommon("page_label", { page }), url: pageUrl }]),
  ];

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    pageUrl,
    breadcrumbs,
  );
  const breadcrumbSchema = generateBreadcrumbSchema(breadcrumbs);
  const itemListSchema = generateItemListSchema(
    hubPage.sections.flatMap((section) =>
      section.items.map((c) => ({
        name: t("automate_with_gaia", { toolA: c.toolA, toolB: c.toolB }),
        url: `${siteConfig.url}/automate/${c.slug}`,
      })),
    ),
  );

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

        <HubSectionNav
          label={tCommon("section_nav_label")}
          sections={hubPage.sections}
        />

        {hubPage.sections.map((section) => (
          <div key={section.id} id={section.id} className="mb-12">
            <h2 className="mb-4 border-b border-zinc-700 pb-2 text-xl font-semibold text-zinc-300">
              {section.label}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {section.items.map((combo) => (
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
          hubPath={HUB_PATH}
          current={page}
          total={pages.length}
          label={tCommon("pagination_label")}
          pageLabel={(n) => tCommon("page_label", { page: n })}
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
