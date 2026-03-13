import { Button } from "@heroui/button";
import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { getTranslations, setRequestLocale } from "next-intl/server";

import JsonLd from "@/components/seo/JsonLd";
import { getTranslatedCombos } from "@/features/integrations/data/getTranslatedCombo";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getAlternates } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generatePageMetadata,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
  }>;
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "automate" });

  const metadata = generatePageMetadata({
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
  });

  return {
    ...metadata,
    alternates: {
      ...metadata.alternates,
      languages: getAlternates("/automate"),
    },
  };
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

export default async function AutomateHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const t = await getTranslations({ locale, namespace: "automate" });
  const tCommon = await getTranslations({ locale, namespace: "common" });

  const allCombos = (await getTranslatedCombos(locale)).filter(
    (c) => !c.canonicalSlug,
  );

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
      description: c.tagline,
    })),
    "Article",
  );

  // Group by first letter of toolA
  const grouped: Record<string, typeof allCombos> = {};
  for (const combo of allCombos) {
    const letter = combo.toolA[0].toUpperCase();
    if (!grouped[letter]) grouped[letter] = [];
    grouped[letter].push(combo);
  }
  const letters = Object.keys(grouped).sort((a, b) => a.localeCompare(b));

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
          {letters.map((letter) => (
            <a
              key={letter}
              href={`#letter-${letter}`}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-800 text-sm font-medium text-zinc-400 transition hover:bg-zinc-700 hover:text-white"
            >
              {letter}
            </a>
          ))}
        </div>

        {/* Grouped combos */}
        {letters.map((letter) => (
          <div key={letter} id={`letter-${letter}`} className="mb-12">
            <h2 className="mb-4 border-b border-zinc-700 pb-2 text-xl font-semibold text-zinc-300">
              {letter}
            </h2>
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {grouped[letter].map((combo) => (
                <Link
                  key={combo.slug}
                  href={`/automate/${combo.slug}`}
                  className="group flex flex-col gap-3 rounded-3xl bg-zinc-800 p-5 transition-all hover:bg-zinc-700/50"
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
                </Link>
              ))}
            </div>
          </div>
        ))}

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
