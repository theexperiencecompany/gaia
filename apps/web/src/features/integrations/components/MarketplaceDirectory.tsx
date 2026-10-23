import Link from "next/link";

import type { CommunityIntegration } from "@/features/integrations/types";

interface MarketplaceDirectoryProps {
  readonly native: readonly CommunityIntegration[];
  readonly community: readonly CommunityIntegration[];
}

interface DirectoryColumnProps {
  readonly heading: string;
  readonly integrations: readonly CommunityIntegration[];
}

function DirectoryColumn({ heading, integrations }: DirectoryColumnProps) {
  if (integrations.length === 0) return null;
  const sorted = [...integrations].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <div>
      <h3 className="mb-4 text-sm font-medium text-zinc-300">{heading}</h3>
      <ul className="columns-2 gap-x-6 text-sm sm:columns-3">
        {sorted.map((integration) => (
          <li key={integration.slug} className="mb-2 break-inside-avoid">
            <Link
              href={`/marketplace/${integration.slug}`}
              className="text-zinc-400 hover:text-white"
            >
              {integration.name}
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Server-rendered A to Z of every integration, so each detail page is one crawlable link from the marketplace. */
export function MarketplaceDirectory({
  native,
  community,
}: MarketplaceDirectoryProps) {
  if (native.length === 0 && community.length === 0) return null;
  return (
    <section className="mt-24">
      <h2 className="mb-8 text-2xl font-medium text-white">All integrations</h2>
      <div className="grid gap-12 md:grid-cols-2">
        <DirectoryColumn heading="Built by GAIA" integrations={native} />
        <DirectoryColumn heading="Community" integrations={community} />
      </div>
    </section>
  );
}
