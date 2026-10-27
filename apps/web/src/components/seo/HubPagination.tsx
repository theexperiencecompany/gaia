import { SiteLink } from "@/components/seo/SiteLink";
import {
  HUB_PAGE_SIZE,
  hubPageCount,
  hubPageHref,
  hubPageSlice,
} from "@/lib/hubPagination";

const PAGE_LINK =
  "flex h-8 min-w-8 items-center justify-center rounded-lg bg-zinc-800 px-2 text-sm font-medium text-zinc-400 transition hover:bg-zinc-700 hover:text-white";
const CURRENT_PAGE =
  "flex h-8 min-w-8 items-center justify-center rounded-lg bg-zinc-700 px-2 text-sm font-medium text-white";

interface HubPaginationProps {
  readonly pathname: string;
  readonly page: number;
  readonly totalPages: number;
}

/** Numbered pager for the hub link lists: every page is a crawlable `<a>`. */
export function HubPagination({
  pathname,
  page,
  totalPages,
}: HubPaginationProps) {
  if (totalPages <= 1) return null;

  return (
    <nav
      aria-label="Pagination"
      className="mt-4 flex flex-wrap items-center justify-center gap-2"
    >
      {page > 1 && (
        <SiteLink
          href={hubPageHref(pathname, page - 1)}
          rel="prev"
          aria-label="← Previous page"
          className={PAGE_LINK}
        >
          ←
        </SiteLink>
      )}
      {Array.from({ length: totalPages }, (_, index) => index + 1).map(
        (pageNumber) =>
          pageNumber === page ? (
            <span key={pageNumber} aria-current="page" className={CURRENT_PAGE}>
              {pageNumber}
            </span>
          ) : (
            <SiteLink
              key={pageNumber}
              href={hubPageHref(pathname, pageNumber)}
              className={PAGE_LINK}
            >
              {pageNumber}
            </SiteLink>
          ),
      )}
      {page < totalPages && (
        <SiteLink
          href={hubPageHref(pathname, page + 1)}
          rel="next"
          aria-label="Next page →"
          className={PAGE_LINK}
        >
          →
        </SiteLink>
      )}
    </nav>
  );
}
