import { PageBreadcrumbs } from "@/components/seo/PageBreadcrumbs";
import { fillCurrentYear } from "@/lib/feature-data";
import type { BestHubConfig } from "./bestAssistantHubConfig";
import type { RankedPick } from "./bestAssistantHubData";

export interface BestHubConfigProps {
  readonly config: BestHubConfig;
}

export interface BestHubRankedProps {
  readonly ranked: readonly RankedPick[];
}

export function BestHubBreadcrumb({ config }: BestHubConfigProps) {
  return (
    <PageBreadcrumbs
      className="mb-8"
      items={[{ label: "Home", href: "/" }, { label: config.breadcrumbName }]}
    />
  );
}

export function BestHubHeader({ config }: BestHubConfigProps) {
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
