import { type HubPage, paginateSections } from "@/lib/hubPagination";
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

/** The /learn hub's pages: terms grouped by category, labelled in the page's locale. */
export function glossaryHubPages<T extends Pick<GlossaryTerm, "category">>(
  terms: readonly T[],
  categoryLabel: (key: GlossaryCategoryLabelKey) => string,
): HubPage<T>[] {
  return paginateSections(
    CATEGORY_LABEL_KEYS.flatMap(([category, labelKey]) => {
      const items = terms.filter((term) => term.category === category);
      return items.length > 0
        ? [
            {
              id: `category-${category}`,
              label: categoryLabel(labelKey),
              items,
            },
          ]
        : [];
    }),
  );
}
