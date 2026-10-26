import { type HubPage, paginateSections } from "@/lib/hubPagination";
import { CATEGORY_ORDER, COMPARISON_CATEGORIES } from "./categories";
import type { ComparisonData } from "./comparisonsData";

const OTHER_CATEGORY = "Other";

function sectionId(category: string): string {
  return `category-${category.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-")}`;
}

/** The /compare hub's pages: comparisons grouped by category, in the hub's category order. */
export function comparisonHubPages<T extends Pick<ComparisonData, "slug">>(
  comparisons: readonly T[],
): HubPage<T>[] {
  const byCategory = new Map<string, T[]>();
  for (const comparison of comparisons) {
    const category = COMPARISON_CATEGORIES[comparison.slug] ?? OTHER_CATEGORY;
    byCategory.set(category, [...(byCategory.get(category) ?? []), comparison]);
  }
  const order: readonly string[] = [...CATEGORY_ORDER, OTHER_CATEGORY];
  return paginateSections(
    order.flatMap((category) => {
      const items = byCategory.get(category);
      return items ? [{ id: sectionId(category), label: category, items }] : [];
    }),
  );
}
