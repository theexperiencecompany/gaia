import { CATEGORY_ORDER, COMPARISON_CATEGORIES } from "./categories";
import type { ComparisonData } from "./comparisonsData";

const OTHER_CATEGORY = "Other";

export interface ComparisonCategoryGroup<T> {
  /** URL segment of /compare/category/<slug>. */
  readonly slug: string;
  readonly label: string;
  readonly items: readonly T[];
}

/** The category a comparison is listed under; uncategorized ones share "Other". */
export function comparisonCategoryOf(
  comparison: Pick<ComparisonData, "slug">,
): string {
  return COMPARISON_CATEGORIES[comparison.slug] ?? OTHER_CATEGORY;
}

function categorySlug(category: string): string {
  return category.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-");
}

/** /compare/category/<slug>: every comparison in one category. */
export function comparisonCategoryPath(slug: string): string {
  return `/compare/category/${slug}`;
}

/** Comparisons grouped by category, in the hub's category order with uncategorized ones last. */
export function comparisonCategoryGroups<
  T extends Pick<ComparisonData, "slug">,
>(comparisons: readonly T[]): ComparisonCategoryGroup<T>[] {
  const byCategory = new Map<string, T[]>();
  for (const comparison of comparisons) {
    const category = comparisonCategoryOf(comparison);
    byCategory.set(category, [...(byCategory.get(category) ?? []), comparison]);
  }
  const order: readonly string[] = [...CATEGORY_ORDER, OTHER_CATEGORY];
  return order.flatMap((category) => {
    const items = byCategory.get(category);
    return items
      ? [{ slug: categorySlug(category), label: category, items }]
      : [];
  });
}
