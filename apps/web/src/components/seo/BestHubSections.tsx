import Link from "next/link";
import ComparisonTable from "@/components/seo/ComparisonTable";
import FAQAccordion from "@/components/seo/FAQAccordion";
import { fillCurrentYear } from "@/lib/feature-data";
import type { BestHubConfig } from "./bestAssistantHubConfig";
import type { RankedPick } from "./bestAssistantHubData";

interface ConfigProps {
  readonly config: BestHubConfig;
}

interface RankedProps {
  readonly ranked: readonly RankedPick[];
}

export function BestHubBreadcrumb({ config }: ConfigProps) {
  return (
    <nav className="mb-8 text-sm text-zinc-500">
      <Link href="/" className="hover:text-zinc-300">
        Home
      </Link>
      <span className="mx-2">/</span>
      <span className="text-zinc-300">{config.breadcrumbName}</span>
    </nav>
  );
}

export function BestHubHeader({ config }: ConfigProps) {
  return (
    <header className="mb-12">
      <h1 className="mb-4 font-serif text-5xl font-normal text-white md:text-6xl">
        {fillCurrentYear(config.heading)}
      </h1>
      <p className="text-xl leading-relaxed text-zinc-400">
        {config.subheading}
      </p>
    </header>
  );
}

export function BestHubIntro({ config }: ConfigProps) {
  return (
    <section className="mb-16 space-y-5 text-lg leading-relaxed text-zinc-300">
      {config.intro}
    </section>
  );
}

export function BestHubTable({ config, ranked }: ConfigProps & RankedProps) {
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

export function BestHubPick({ config }: ConfigProps) {
  return (
    <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
      <h2 className="mb-4 text-2xl font-semibold text-white">Our pick: GAIA</h2>
      <p className="mb-4 text-lg leading-relaxed text-zinc-300">
        {config.pickBody}
      </p>
      <div className="flex flex-wrap gap-4 text-sm">
        <Link
          href={config.pickCompareHref}
          className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
        >
          {config.pickCompareLabel}
        </Link>
        <Link
          href={config.pickAlternativeHref}
          className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
        >
          {config.pickAlternativeLabel}
        </Link>
      </div>
    </section>
  );
}

export function BestHubFaq({ config }: ConfigProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        Common questions
      </h2>
      <FAQAccordion faqs={config.faqs} />
    </section>
  );
}
