import ComparisonTable from "@/components/seo/ComparisonTable";
import type { BestHubConfigProps, BestHubRankedProps } from "./BestHubSections";

export function BestHubIntro({ config }: BestHubConfigProps) {
  return (
    <section className="mb-16 space-y-5 text-lg leading-relaxed text-zinc-300">
      {config.intro}
    </section>
  );
}

export function BestHubTable({
  config,
  ranked,
}: BestHubConfigProps & BestHubRankedProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        {config.tableTitle}
      </h2>
      <ComparisonTable
        ariaLabel={config.tableAriaLabel}
        columns={[
          {
            key: "rank",
            label: "#",
            headerClassName: "text-zinc-500",
            cellClassName: "font-medium text-zinc-300",
          },
          {
            key: "assistant",
            label: "Assistant",
            headerClassName: "text-primary",
            cellClassName: "font-medium text-white",
          },
          {
            key: "bestFor",
            label: "Best for",
            headerClassName: "text-zinc-500",
            cellClassName: "text-zinc-300",
          },
          {
            key: "take",
            label: "The short version",
            headerClassName: "text-zinc-500",
            cellClassName: "text-zinc-400",
          },
        ]}
        rows={[
          {
            rank: "1",
            assistant: "GAIA (our pick)",
            bestFor: config.gaiaBestFor,
            take: config.gaiaTake,
          },
          ...ranked.map((pick, index) => ({
            rank: String(index + 2),
            assistant: pick.data.name,
            bestFor: config.bestFor[pick.data.slug] ?? pick.data.tagline,
            take: config.shortVersion[pick.data.slug] ?? pick.data.tagline,
          })),
        ]}
      />
    </section>
  );
}
