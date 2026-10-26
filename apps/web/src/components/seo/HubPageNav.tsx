import Link from "next/link";
import { SiteLink } from "@/components/seo/SiteLink";
import { hubPagePath } from "@/lib/hubPagination";

const NAV_ITEM_CLASS =
  "flex h-8 min-w-8 items-center justify-center gap-1.5 rounded-lg px-3 text-sm font-medium transition";

export interface HubIndexEntry {
  /** Fragment id of the group's section on the hub. */
  readonly id: string;
  readonly label: string;
  readonly count: number;
}

/** Jump links to a hub's groups, each with how many pages it holds. */
export function HubIndex({
  label,
  entries,
}: {
  readonly label: string;
  readonly entries: readonly HubIndexEntry[];
}) {
  return (
    <nav aria-label={label} className="mb-12 flex flex-wrap gap-2">
      {entries.map((entry) => (
        <Link
          key={entry.id}
          href={`#${entry.id}`}
          className={`${NAV_ITEM_CLASS} rounded-full bg-zinc-800 text-zinc-300 hover:bg-zinc-700 hover:text-white`}
        >
          {entry.label}
          <span className="text-zinc-500">{entry.count}</span>
        </Link>
      ))}
    </nav>
  );
}

/** Links to every page of a hub, so each child stays one crawlable link from the hub. */
export function HubPagination({
  hubPath,
  current,
  total,
  label,
  pageLabel,
}: {
  readonly hubPath: string;
  readonly current: number;
  readonly total: number;
  readonly label: string;
  readonly pageLabel: (page: number) => string;
}) {
  if (total <= 1) return null;
  const pages = Array.from({ length: total }, (_, index) => index + 1);
  return (
    <nav aria-label={label} className="mt-4 mb-12 flex flex-wrap gap-2">
      {pages.map((page) =>
        page === current ? (
          <span
            key={page}
            aria-current="page"
            className={`${NAV_ITEM_CLASS} bg-primary/10 text-primary`}
          >
            {page}
          </span>
        ) : (
          <SiteLink
            key={page}
            href={hubPagePath(hubPath, page)}
            aria-label={pageLabel(page)}
            className={`${NAV_ITEM_CLASS} bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-white`}
          >
            {page}
          </SiteLink>
        ),
      )}
    </nav>
  );
}
