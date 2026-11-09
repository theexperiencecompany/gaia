import type { GlossaryTerm } from "./glossaryData";

/** The /learn hub's categories in display order, each with its glossary message key. */
const CATEGORY_LABEL_KEYS = [
  ["ai-concepts", "category_ai_concepts"],
  ["productivity", "category_productivity"],
  ["automation", "category_automation"],
  ["email", "category_email"],
  ["calendar", "category_calendar"],
  ["task-management", "category_task_management"],
  ["knowledge-management", "category_knowledge_management"],
  ["development", "category_development"],
] as const;

type GlossaryCategoryLabelKey = (typeof CATEGORY_LABEL_KEYS)[number][1];

export interface GlossaryCategoryGroup<T> {
  /** URL segment of /learn/category/<slug>: the category key. */
  readonly slug: string;
  readonly label: string;
  readonly items: readonly T[];
}

/** /learn/category/<slug>: every term in one category. */
export function glossaryCategoryPath(slug: string): string {
  return `/learn/category/${slug}`;
}

/** Terms grouped by category in the hub's order, labelled in the page's locale. */
export function glossaryCategoryGroups<
  T extends Pick<GlossaryTerm, "category">,
>(
  terms: readonly T[],
  categoryLabel: (key: GlossaryCategoryLabelKey) => string,
): GlossaryCategoryGroup<T>[] {
  return CATEGORY_LABEL_KEYS.flatMap(([category, labelKey]) => {
    const items = terms.filter((term) => term.category === category);
    return items.length > 0
      ? [{ slug: category, label: categoryLabel(labelKey), items }]
      : [];
  });
}
