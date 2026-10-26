import { Button } from "@heroui/button";
import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { HubIndex } from "@/components/seo/HubPageNav";
import JsonLd from "@/components/seo/JsonLd";
import { RelatedAutomationsGrid } from "@/components/seo/RelatedAutomationsGrid";
import { getTranslatedCombos } from "@/features/integrations/data/getTranslatedCombo";
import {
  appPagePath,
  comboAppGroups,
} from "@/features/integrations/lib/comboApps";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

/** Combos each app's section previews: 24 apps at 2 each plus their "all" links keep the hub under 100 links. */
const COMBOS_PER_APP = 2;

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

function appSectionId(appSlug: string): string {
  return `app-${appSlug}`;
}

export default async function AutomateHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, tCommon, allCombos] = await Promise.all([
    getTranslations({ locale, namespace: "automate" }),
    getTranslations({ locale, namespace: "common" }),
    getTranslatedCombos(locale),
  ]);
  // getTranslatedCombos is _slugs-driven: consolidated victims (which 308 via
  // canonical-redirects.mjs) are already excluded — no marker filter needed.
  const apps = comboAppGroups(allCombos);

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
    apps.map((app) => ({
      name: t("app_page_title", { app: app.name }),
      url: `${siteConfig.url}${appPagePath(app.slug)}`,
    })),
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

        <HubIndex
          label={tCommon("section_nav_label")}
          entries={apps.map((app) => ({
            id: appSectionId(app.slug),
            label: app.name,
            count: app.combos.length,
          }))}
        />

        {apps.map((app) => (
          <RelatedAutomationsGrid
            key={app.slug}
            id={appSectionId(app.slug)}
            heading={app.name}
            headingClassName="text-2xl font-semibold text-white"
            combos={app.combos.slice(0, COMBOS_PER_APP)}
            allLink={{
              href: appPagePath(app.slug),
              label: t("all_app_automations", {
                count: app.combos.length,
                app: app.name,
              }),
            }}
          />
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
