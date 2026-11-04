import Link from "next/link";

import { HubPagination } from "@/components/seo/HubPageNav";
import { MARKETPLACE_PATH } from "@/features/integrations/lib/marketplaceDirectoryPages";
import type { CommunityIntegration } from "@/features/integrations/types";
import type { HubPage, HubSection } from "@/lib/hubPagination";

interface MarketplaceDirectoryProps {
  readonly hubPage: HubPage<CommunityIntegration>;
  readonly totalPages: number;
}

function DirectoryColumn({
  section,
}: {
  readonly section: HubSection<CommunityIntegration>;
}) {
  return (
    <div id={section.id}>
      <h3 className="mb-4 text-sm font-medium text-zinc-300">
        {section.label}
      </h3>
      <ul className="columns-2 gap-x-6 text-sm sm:columns-3">
        {section.items.map((integration) => (
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

/** Server-rendered A to Z of every integration across the directory's pages, so each detail page is one crawlable link from the marketplace. */
export function MarketplaceDirectory({
  hubPage,
  totalPages,
}: MarketplaceDirectoryProps) {
  return (
    <section className="mt-24">
      <h2 className="mb-8 text-2xl font-medium text-white">All integrations</h2>
      <div className="mb-12 grid gap-12 md:grid-cols-2">
        {hubPage.sections.map((section) => (
          <DirectoryColumn key={section.id} section={section} />
        ))}
      </div>
      <HubPagination
        hubPath={MARKETPLACE_PATH}
        current={hubPage.page}
        total={totalPages}
        label="Integration directory pages"
        pageLabel={(page) => `Integration directory, page ${page}`}
      />
    </section>
  );
}
