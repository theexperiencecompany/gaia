import type { CommunityIntegration } from "@/features/integrations/types";

/** How many related integrations a marketplace page links. */
export const RELATED_INTEGRATIONS_LIMIT = 6;

type Placed = Pick<CommunityIntegration, "slug" | "category">;

/** The items after the one at `index`, wrapping round to the start; all of them when `index` is -1. */
function rotatedAfter<T>(items: readonly T[], index: number): T[] {
  return [...items.slice(index + 1), ...items.slice(0, Math.max(index, 0))];
}

function categoryFirst<T extends Placed>(
  items: readonly T[],
  category: string,
): T[] {
  return [
    ...items.filter((item) => item.category === category),
    ...items.filter((item) => item.category !== category),
  ];
}

/**
 * The integrations a marketplace page links as related. Each list starts after
 * the current integration, so every page is linked from its neighbours instead
 * of all pages pointing at the same top few. A native page links GAIA's other
 * integrations, its category first; a community page links its category's
 * community siblings, then GAIA's integrations, its category first.
 */
export function relatedIntegrations<T extends Placed>(
  current: Placed,
  native: readonly T[],
  community: readonly T[],
  limit: number = RELATED_INTEGRATIONS_LIMIT,
): T[] {
  const nativeIndex = native.findIndex((item) => item.slug === current.slug);
  const pool =
    nativeIndex >= 0
      ? categoryFirst(rotatedAfter(native, nativeIndex), current.category)
      : [
          ...rotatedAfter(
            community,
            community.findIndex((item) => item.slug === current.slug),
          ).filter((item) => item.category === current.category),
          ...categoryFirst(native, current.category),
        ];
  return pool.filter((item) => item.slug !== current.slug).slice(0, limit);
}
