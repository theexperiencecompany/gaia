import { CircleArrowRight02Icon } from "@icons";
import type { Metadata } from "next";
import { getTranslations, setRequestLocale } from "next-intl/server";
import JsonLd from "@/components/seo/JsonLd";
import { SiteLink } from "@/components/seo/SiteLink";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import { getTranslatedPersonas } from "@/features/personas/data/getTranslatedPersona";
import { generateLocalizedPageMetadata } from "@/i18n/getAlternates";
import {
  generateBreadcrumbSchema,
  generateItemListSchema,
  generateWebPageSchema,
  siteConfig,
} from "@/lib/seo";

interface PageProps {
  readonly params: Promise<{ readonly locale: string }>;
}

const FEATURED_SLUGS = new Set([
  "startup-founders",
  "software-developers",
  "sales-professionals",
  "product-managers",
  "engineering-managers",
  "agency-owners",
]);

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations({ locale, namespace: "personas" });
  return generateLocalizedPageMetadata({
    title: t("hub_meta_title"),
    description: t("hub_meta_description"),
    path: "/for",
    keywords: [
      "AI assistant for professionals",
      "role-based AI assistant",
      "AI productivity by role",
      "GAIA use cases by profession",
      "AI assistant for teams",
      "professional AI automation",
    ],
    locale,
  });
}

export default async function PersonasHubPage({ params }: PageProps) {
  const { locale } = await params;
  setRequestLocale(locale);
  const [t, personas] = await Promise.all([
    getTranslations({ locale, namespace: "personas" }),
    getTranslatedPersonas(locale),
  ]);

  const webPageSchema = generateWebPageSchema(
    t("hub_title"),
    t("hub_subtitle"),
    `${siteConfig.url}/for`,
    [
      { name: "Home", url: siteConfig.url },
      { name: t("hub_title"), url: `${siteConfig.url}/for` },
    ],
  );

  const breadcrumbSchema = generateBreadcrumbSchema([
    { name: "Home", url: siteConfig.url },
    { name: t("hub_title"), url: `${siteConfig.url}/for` },
  ]);

  const itemListSchema = generateItemListSchema(
    personas.map((p) => ({
      name: p.title,
      url: `${siteConfig.url}/for/${p.slug}`,
    })),
  );

  const heroPersona = personas.find((p) => p.slug === "startup-founders");
  const featuredPersonas = personas.filter(
    (p) => FEATURED_SLUGS.has(p.slug) && p.slug !== "startup-founders",
  );
  const otherPersonas = personas.filter((p) => !FEATURED_SLUGS.has(p.slug));

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
        </header>

        {/* Featured Experiences */}
        <section className="mb-16">
          <p className="mb-4 text-[11px] font-semibold uppercase tracking-widest text-zinc-500">
            {t("featured_experiences")}
          </p>

          {/* Hero card */}
          {heroPersona && (
            <SiteLink
              href="/for/startup-founders"
              className="group mb-4 flex flex-col gap-3 rounded-3xl bg-primary/10 p-6 transition-colors hover:bg-primary/15"
            >
              <div className="flex items-center gap-3">
                <h2 className="text-2xl font-semibold text-primary">
                  {heroPersona.role}
                </h2>
              </div>
              <p className="max-w-2xl text-sm leading-relaxed text-zinc-300">
                {heroPersona.metaDescription}
              </p>
              <span className="flex items-center gap-1.5 text-sm font-medium text-primary">
                {t("see_full_experience")}
                <CircleArrowRight02Icon width={17} height={17} />
              </span>
            </SiteLink>
          )}

          {/* Other featured */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {featuredPersonas.map((persona) => (
              <SiteLink
                key={persona.slug}
                href={`/for/${persona.slug}`}
                className="group flex flex-col gap-2 rounded-3xl bg-primary/10 p-5 transition-colors hover:bg-primary/15"
              >
                <h2 className="text-xl font-semibold text-primary transition-colors">
                  {persona.role}
                </h2>
                <p className="flex-1 text-sm leading-relaxed text-zinc-300">
                  {persona.metaDescription}
                </p>
                <span className="mt-1 flex items-center gap-1.5 text-sm font-medium text-primary">
                  {t("see_full_experience")}
                  <CircleArrowRight02Icon width={17} height={17} />
                </span>
              </SiteLink>
            ))}
          </div>
        </section>

        {/* All other roles */}
        {otherPersonas.length > 0 && (
          <section>
            <p className="mb-4 text-[11px] font-semibold uppercase tracking-widest text-zinc-500">
              {t("all_roles")}
            </p>
            <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
              {otherPersonas.map((persona) => (
                <SiteLink
                  key={persona.slug}
                  href={`/for/${persona.slug}`}
                  className="group flex flex-col gap-2 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
                >
                  <h2 className="text-base font-semibold text-white transition-colors group-hover:text-primary">
                    {persona.role}
                  </h2>
                  <p className="flex-1 text-sm leading-relaxed text-zinc-400">
                    {persona.metaDescription}
                  </p>
                  <span className="mt-1 flex items-center gap-1 text-xs text-zinc-500 transition-colors group-hover:text-zinc-300">
                    {t("read_more")}
                    <CircleArrowRight02Icon width={14} height={14} />
                  </span>
                </SiteLink>
              ))}
            </div>
          </section>
        )}
      </div>
      <FinalSection />
    </>
  );
}
