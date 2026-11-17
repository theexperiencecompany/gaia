import { SiteLink } from "@/components/seo/SiteLink";
import { VersusLogos } from "@/components/seo/VersusLogos";
import type { ComparisonData } from "@/features/comparisons/data/comparisonsData";
import { hubCardLoading } from "@/lib/hubPagination";

type ComparisonCardData = Pick<
  ComparisonData,
  "slug" | "name" | "domain" | "tagline" | "description"
>;

/** Cards linking /compare pages, each led by GAIA's logo tilted against the tool's. */
export function ComparisonCardGrid({
  comparisons,
  vsLabel,
  headingLevel,
  section,
}: {
  readonly comparisons: readonly ComparisonCardData[];
  readonly vsLabel: (name: string) => string;
  /** h2 where the cards sit directly under the page h1, h3 under a section heading. */
  readonly headingLevel: "h2" | "h3";
  /** The grid's place among the page's sections: the first one's first row opens in view. */
  readonly section: number;
}) {
  const Heading = headingLevel;
  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
      {comparisons.map((comparison, index) => (
        <SiteLink
          key={comparison.slug}
          href={`/compare/${comparison.slug}`}
          className="group flex flex-col gap-3 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <VersusLogos
            name={comparison.name}
            domain={comparison.domain}
            loading={hubCardLoading(section, index)}
          />
          <Heading className="text-lg font-medium text-white transition-colors group-hover:text-accent">
            {vsLabel(comparison.name)}
          </Heading>
          <p className="text-sm text-zinc-500">{comparison.tagline}</p>
          <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
            {comparison.description}
          </p>
        </SiteLink>
      ))}
    </div>
  );
}
