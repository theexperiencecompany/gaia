import { FEATURED_USE_CASE_CATEGORY } from "@/features/use-cases/constants";

/** How many related use cases a use-case page links. */
export const RELATED_USE_CASES_LIMIT = 6;

interface Placed {
  readonly slug: string;
  readonly categories?: readonly string[] | null;
}

/** The page's topic: its first category that is not the featured tag. */
function primaryCategory(useCase: Placed | undefined): string {
  return (
    useCase?.categories?.find(
      (category) => category !== FEATURED_USE_CASE_CATEGORY,
    ) ?? FEATURED_USE_CASE_CATEGORY
  );
}

/**
 * The curated use cases a use-case page links as related. The list starts after
 * the current one, so every use case is linked from its neighbours instead of
 * all pages pointing at the same most-run few, and its own category comes first.
 * A community workflow is not in the list, so it gets the featured ones first.
 */
export function relatedUseCases<T extends Placed>(
  current: Pick<Placed, "slug">,
  explore: readonly T[],
  limit: number = RELATED_USE_CASES_LIMIT,
): T[] {
  const index = explore.findIndex((item) => item.slug === current.slug);
  const category = primaryCategory(explore[index]);
  const after = [
    ...explore.slice(index + 1),
    ...explore.slice(0, Math.max(index, 0)),
  ];
  const inCategory = (item: T) => item.categories?.includes(category) ?? false;
  return [
    ...after.filter(inCategory),
    ...after.filter((item) => !inCategory(item)),
  ].slice(0, limit);
}
