import Link from "next/link";

import { MARKETING_PAGES } from "@/lib/marketingPages";

const BEST_HUB_PREFIX = "/best-ai-";

/** The other best-of rankings, so each hub links the rest instead of leaving them reachable only from the sitemap. */
export function BestHubSiblingLinks({
  currentPath,
}: {
  readonly currentPath: string;
}) {
  const siblings = MARKETING_PAGES.filter(
    (page) =>
      page.path.startsWith(BEST_HUB_PREFIX) && page.path !== currentPath,
  );
  return (
    <section className="mb-16">
      <h2 className="mb-4 text-3xl font-semibold text-white">
        More buyer's guides
      </h2>
      <ul className="space-y-2 text-zinc-400">
        {siblings.map((page) => (
          <li key={page.path}>
            <Link
              href={page.path}
              className="underline underline-offset-2 hover:text-zinc-200"
            >
              {page.title}
            </Link>
            <span className="text-zinc-500">: {page.description}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
