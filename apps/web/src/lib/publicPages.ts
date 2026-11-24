/** Route segments whose cached pages go stale together, as revalidatePath names them. */
export interface PublicPageRoute {
  readonly route: string;
  readonly type: "layout" | "page";
}

/**
 * The cached public pages that show each kind of API data. The API names the
 * data that changed with one of these keys (its PublicPageDomain enum, in
 * apps/api/app/constants/public_pages.py). A page outside this map rebuilds
 * on its own `revalidate` timer alone.
 */
export const PUBLIC_PAGE_ROUTES = {
  integrations: [{ route: "/[locale]/(landing)/marketplace", type: "layout" }],
  workflows: [
    { route: "/[locale]/(landing)/use-cases", type: "layout" },
    // An integration's page lists the community workflows that use it.
    { route: "/[locale]/(landing)/marketplace/[slug]", type: "page" },
  ],
} as const satisfies Record<string, readonly PublicPageRoute[]>;

export type PublicPageDomain = keyof typeof PUBLIC_PAGE_ROUTES;

/** Next's prefix on the tag every cached page carries for each layout and page of its route. */
const ROUTE_TAG_PREFIX = "_N_T_";

/** The cache tags revalidatePath writes for PUBLIC_PAGE_ROUTES: the only tags the tag cache stores or looks up. */
export const PUBLIC_PAGE_TAGS: ReadonlySet<string> = new Set(
  Object.values(PUBLIC_PAGE_ROUTES)
    .flat()
    .map(({ route, type }) => `${ROUTE_TAG_PREFIX}${route}/${type}`),
);

export function isPublicPageDomain(value: unknown): value is PublicPageDomain {
  return typeof value === "string" && Object.hasOwn(PUBLIC_PAGE_ROUTES, value);
}
