import Image from "next/image";
import { SiteLink } from "@/components/seo/SiteLink";
import type { ComparisonData } from "@/features/comparisons/data/comparisonsData";

type ComparisonCardData = Pick<
  ComparisonData,
  "slug" | "name" | "domain" | "tagline" | "description"
>;

/** Cards linking /compare pages, each led by GAIA's logo tilted against the tool's. */
export function ComparisonCardGrid({
  comparisons,
  vsLabel,
}: {
  readonly comparisons: readonly ComparisonCardData[];
  readonly vsLabel: (name: string) => string;
}) {
  return (
    <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
      {comparisons.map((comparison) => (
        <SiteLink
          key={comparison.slug}
          href={`/compare/${comparison.slug}`}
          className="group flex flex-col gap-3 rounded-3xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
        >
          <div className="flex items-center -space-x-2">
            <div
              className="relative flex h-9 w-9 items-center justify-center p-0"
              style={{ rotate: "-9deg", zIndex: 1 }}
            >
              <Image
                src="/images/logos/macos.webp"
                alt="GAIA"
                width={50}
                height={50}
              />
            </div>
            <div
              className="relative flex h-8 w-8 items-center justify-center rounded-md overflow-hidden p-0"
              style={{ rotate: "9deg", zIndex: 0 }}
            >
              <Image
                src={`https://www.google.com/s2/favicons?domain=${comparison.domain}&sz=128`}
                alt={comparison.name}
                width={40}
                height={40}
                unoptimized
              />
            </div>
          </div>
          <h3 className="text-lg font-medium text-white transition-colors group-hover:text-primary">
            {vsLabel(comparison.name)}
          </h3>
          <p className="text-sm text-zinc-500">{comparison.tagline}</p>
          <p className="line-clamp-2 text-sm leading-relaxed text-zinc-400">
            {comparison.description}
          </p>
        </SiteLink>
      ))}
    </div>
  );
}
