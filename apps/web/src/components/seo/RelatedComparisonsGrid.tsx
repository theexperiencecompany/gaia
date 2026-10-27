import { getTranslations } from "next-intl/server";

import { SiteLink } from "@/components/seo/SiteLink";
import { getTranslatedComparison } from "@/features/comparisons/data/getTranslatedComparison";
import { canonicalHref } from "@/lib/canonicalLinks";

interface RelatedComparisonsGridProps {
  readonly heading: string;
  readonly slugs: readonly string[];
}

/** Cards linking the comparisons a page relates to, each at its live URL and deduplicated after consolidation. */
export async function RelatedComparisonsGrid({
  heading,
  slugs,
}: RelatedComparisonsGridProps) {
  const [t, comparisons] = await Promise.all([
    getTranslations("comparisons"),
    Promise.all(slugs.map((slug) => getTranslatedComparison(slug))),
  ]);
  const cards = new Map<string, { name: string; tagline: string }>();
  for (const comparison of comparisons) {
    if (comparison === undefined) continue;
    const href = canonicalHref(`/compare/${comparison.slug}`);
    if (!cards.has(href)) cards.set(href, comparison);
  }
  if (cards.size === 0) return null;

  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">{heading}</h2>
      <div className="grid gap-4 sm:grid-cols-3">
        {[...cards].map(([href, comparison]) => (
          <SiteLink
            key={href}
            href={href}
            className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <h3 className="mb-1 text-base font-medium text-white group-hover:text-primary">
              {t("gaia_vs", { name: comparison.name })}
            </h3>
            <p className="text-xs text-zinc-400">{comparison.tagline}</p>
          </SiteLink>
        ))}
      </div>
    </section>
  );
}
