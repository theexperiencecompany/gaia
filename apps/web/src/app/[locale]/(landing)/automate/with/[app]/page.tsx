import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations, setRequestLocale } from "next-intl/server";
import { ComboAppIcon } from "@/components/seo/ComboAppIcons";
import { HubBreadcrumb } from "@/components/seo/HubBreadcrumb";
import JsonLd from "@/components/seo/JsonLd";
import { RelatedAutomationsGrid } from "@/components/seo/RelatedAutomationsGrid";
import { getAllCombos } from "@/features/integrations/data/combosData";
import { getTranslatedCombos } from "@/features/integrations/data/getTranslatedCombo";
import {
  appPagePath,
  comboAppGroups,
} from "@/features/integrations/lib/comboApps";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import { prerenderedMarketingParams } from "@/lib/selfhost";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{
    readonly locale: string;
    readonly app: string;
  }>;
}

export function generateStaticParams() {
  return prerenderedMarketingParams(async () =>
    comboAppGroups(await getAllCombos()).map((app) => ({ app: app.slug })),
  );
}

export const dynamicParams = false;

async function findApp(appSlug: string, locale?: string) {
  const apps = comboAppGroups(await getTranslatedCombos(locale));
  return apps.find((app) => app.slug === appSlug);
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale, app: appSlug } = await params;
  const [t, app] = await Promise.all([
    getTranslations({ locale, namespace: "automate" }),
    findApp(appSlug, locale),
  ]);
  if (!app) return {};
  const values = { app: app.name, count: app.combos.length };
  return generateLocalizedPageMetadata({
    title: t("app_meta_title", values),
    description: t("app_meta_description", values),
    path: appPagePath(app.slug),
    keywords: [
      `${app.name} automation`,
      `automate ${app.name}`,
      `${app.name} AI integration`,
      `${app.name} workflows`,
    ],
    locale,
  });
}

export default async function AutomateAppPage({ params }: PageProps) {
  const { locale, app: appSlug } = await params;
  setRequestLocale(locale);
  const [t, tCommon, app] = await Promise.all([
    getTranslations({ locale, namespace: "automate" }),
    getTranslations({ locale, namespace: "common" }),
    findApp(appSlug, locale),
  ]);
  if (!app) notFound();

  const pageUrl = `${siteConfig.url}${appPagePath(app.slug)}`;
  const title = t("app_page_title", { app: app.name });
  const subtitle = t("app_page_subtitle", {
    app: app.name,
    count: app.combos.length,
  });
  const breadcrumbs = [
    { name: "Home", url: siteConfig.url },
    { name: t("breadcrumb"), url: `${siteConfig.url}/automate` },
    { name: title, url: pageUrl },
  ];

  return (
    <>
      <JsonLd
        data={[
          generateWebPageSchema(title, subtitle, pageUrl, breadcrumbs),
          generateBreadcrumbSchema(breadcrumbs),
          generateItemListSchema(
            app.combos.map((combo) => ({
              name: t("automate_with_gaia", {
                toolA: combo.toolA,
                toolB: combo.toolB,
              }),
              url: `${siteConfig.url}/automate/${combo.slug}`,
            })),
          ),
        ]}
      />

      <div className="mx-auto max-w-5xl px-6 pt-36 pb-24">
        <HubBreadcrumb
          crumbs={[
            { label: tCommon("home"), href: "/" },
            { label: t("breadcrumb"), href: "/automate" },
            { label: app.name },
          ]}
        />

        <header className="mb-16">
          <h1 className="mb-4 flex items-center gap-4 font-serif text-5xl font-normal text-white md:text-6xl">
            <ComboAppIcon app={app} size={48} />
            {title}
          </h1>
          <p className="max-w-2xl text-xl text-zinc-400">{subtitle}</p>
        </header>

        <RelatedAutomationsGrid
          heading={t("all_app_automations", {
            count: app.combos.length,
            app: app.name,
          })}
          headingClassName="text-2xl font-semibold text-white"
          combos={app.combos}
        />
      </div>

      <FinalSection />
    </>
  );
}
