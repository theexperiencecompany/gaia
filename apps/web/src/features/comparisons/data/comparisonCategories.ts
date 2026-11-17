import {
  CATEGORY_ORDER,
  COMPARISON_CATEGORIES,
  type ComparisonCategory,
} from "./categories";
import type { ComparisonData } from "./comparisonsData";

const OTHER_CATEGORY = "Other";

type ComparisonCategoryKey = ComparisonCategory | typeof OTHER_CATEGORY;

/** Each category's comparisons message key: the category key stays English, its label is the page's locale. */
const CATEGORY_LABEL_KEYS = {
  "AI Assistants": "category_ai_assistants",
  Automation: "category_automation",
  "Task Management": "category_task_management",
  "Project Management": "category_project_management",
  "Calendar & Scheduling": "category_calendar_scheduling",
  Email: "category_email",
  "Notes & Knowledge": "category_notes_knowledge",
  [OTHER_CATEGORY]: "category_other",
} as const satisfies Record<ComparisonCategoryKey, string>;

type ComparisonCategoryLabelKey =
  (typeof CATEGORY_LABEL_KEYS)[ComparisonCategoryKey];

export interface ComparisonCategoryGroup<T> {
  /** URL segment of /compare/category/<slug>. */
  readonly slug: string;
  readonly label: string;
  readonly items: readonly T[];
}

/** The category a comparison is listed under; uncategorized ones share "Other". */
export function comparisonCategoryOf(
  comparison: Pick<ComparisonData, "slug">,
): ComparisonCategoryKey {
  return COMPARISON_CATEGORIES[comparison.slug] ?? OTHER_CATEGORY;
}

function categorySlug(category: string): string {
  return category.toLowerCase().replaceAll(/[^a-z0-9]+/g, "-");
}

/** /compare/category/<slug>: every comparison in one category. */
export function comparisonCategoryPath(slug: string): string {
  return `/compare/category/${slug}`;
}

/** Comparisons grouped by category in the hub's order with uncategorized ones last, labelled in the page's locale. */
export function comparisonCategoryGroups<
  T extends Pick<ComparisonData, "slug">,
>(
  comparisons: readonly T[],
  categoryLabel: (key: ComparisonCategoryLabelKey) => string,
): ComparisonCategoryGroup<T>[] {
  const byCategory = new Map<ComparisonCategoryKey, T[]>();
  for (const comparison of comparisons) {
    const category = comparisonCategoryOf(comparison);
    byCategory.set(category, [...(byCategory.get(category) ?? []), comparison]);
  }
  const order: readonly ComparisonCategoryKey[] = [
    ...CATEGORY_ORDER,
    OTHER_CATEGORY,
  ];
  return order.flatMap((category) => {
    const items = byCategory.get(category);
    return items
      ? [
          {
            slug: categorySlug(category),
            label: categoryLabel(CATEGORY_LABEL_KEYS[category]),
            items,
          },
        ]
      : [];
  });
}
