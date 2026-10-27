import Link from "next/link";
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
    <nav className="mb-8 text-sm text-zinc-500">
      <Link href="/" className="hover:text-zinc-300">
        Home
      </Link>
      <span className="mx-2">/</span>
      <span className="text-zinc-300">{config.breadcrumbName}</span>
    </nav>
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
