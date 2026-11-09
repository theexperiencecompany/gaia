/**
 * Links rendered per hub page. With the navbar, footer, section and page
 * links, a page stays within 100 internal links; each card is also duplicated
 * into the RSC flight payload, so an unbounded list costs roughly twice its
 * markup.
 */
export const HUB_PAGE_SIZE = 40;

/** The path segment that holds a hub's later pages: /automate/page/2. */
const PAGE_SEGMENT = "page";

export interface HubSection<T> {
  /** Fragment id the section navigation links to. */
  readonly id: string;
  readonly label: string;
  readonly items: readonly T[];
}

export interface HubPage<T> {
  /** 1-based page number. */
  readonly page: number;
  readonly sections: readonly HubSection<T>[];
}

function chunk<T>(items: readonly T[], size: number): T[][] {
  return Array.from({ length: Math.ceil(items.length / size) }, (_, index) =>
    items.slice(index * size, (index + 1) * size),
  );
}

/** Pack whole sections into pages of at most HUB_PAGE_SIZE items, splitting only a section larger than a page. */
export function paginateSections<T>(
  sections: readonly HubSection<T>[],
): HubPage<T>[] {
  const pages: HubSection<T>[][] = [];
  let current: HubSection<T>[] = [];
  let currentSize = 0;
  for (const section of sections) {
    for (const items of chunk(section.items, HUB_PAGE_SIZE)) {
      if (currentSize + items.length > HUB_PAGE_SIZE) {
        pages.push(current);
        current = [];
        currentSize = 0;
      }
      current.push({ ...section, items });
      currentSize += items.length;
    }
  }
  if (current.length > 0) pages.push(current);
  return pages.map((pageSections, index) => ({
    page: index + 1,
    sections: pageSections,
  }));
}

/** A hub page's path: the hub itself for page 1, /<hub>/page/<n> after it. */
export function hubPagePath(hubPath: string, page: number): string {
  return page === 1 ? hubPath : `${hubPath}/${PAGE_SEGMENT}/${page}`;
}

/** `/automate` for the first page, `/automate/page/2` after it — plain links, no client state. */
export function hubPageHref(pathname: string, page: number): string {
  return page <= 1 ? pathname : `${pathname}/page/${page}`;
}

export function hubPageCount(totalItems: number): number {
  return Math.max(1, Math.ceil(totalItems / HUB_PAGE_SIZE));
}

export function hubPageSlice<T>(items: readonly T[], page: number): T[] {
  return items.slice((page - 1) * HUB_PAGE_SIZE, page * HUB_PAGE_SIZE);
}

/** Static params for /<hub>/page/[page]: every page after the first. */
export function laterHubPageParams<T>(
  pages: readonly HubPage<T>[],
): { page: string }[] {
  return pages
    .filter((page) => page.page > 1)
    .map((page) => ({ page: String(page.page) }));
}
