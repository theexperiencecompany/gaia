/** Links rendered per hub page. Each card is duplicated into the RSC flight payload, so an unbounded list costs roughly twice its markup. */
export const HUB_PAGE_SIZE = 40;

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
