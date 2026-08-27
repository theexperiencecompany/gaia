/**
 * Integration category utilities
 *
 * Categories are derived dynamically from backend integrations data.
 * This file provides the browse taxonomy, display labels, and utility
 * functions — the single source of truth for category presentation.
 */

export interface IntegrationCategory {
  key: string;
  label: string;
}

/**
 * Browse taxonomy for the marketplace filter chips.
 */
export const INTEGRATION_CATEGORIES: IntegrationCategory[] = [
  { key: "all", label: "All" },
  { key: "productivity", label: "Productivity" },
  { key: "communication", label: "Communication" },
  { key: "developer", label: "Developer" },
  { key: "analytics", label: "Analytics" },
  { key: "finance", label: "Finance" },
  { key: "ai-ml", label: "AI & ML" },
  { key: "education", label: "Education" },
  { key: "personal", label: "Personal" },
  { key: "capabilities", label: "Capabilities" },
  { key: "other", label: "Other" },
];

/**
 * Get display label for a category ID
 */
export function getCategoryLabel(categoryId: string): string {
  return categoryId
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Extract unique categories from integrations data
 */
export function getUniqueCategories(
  integrations: { category: string }[],
): string[] {
  const categories = new Set(integrations.map((i) => i.category));
  return Array.from(categories);
}

/**
 * Preferred display order for categories (those not listed appear at the end)
 */
const CATEGORY_DISPLAY_PRIORITY: Record<string, number> = {
  created_by_you: 0,
  productivity: 1,
  developer: 2,
  business: 3,
  social: 4,
  communication: 5,
};

/**
 * Sort categories by display priority
 */
export function sortCategories(categories: string[]): string[] {
  return categories.toSorted((a, b) => {
    const priorityA = CATEGORY_DISPLAY_PRIORITY[a] ?? 100;
    const priorityB = CATEGORY_DISPLAY_PRIORITY[b] ?? 100;
    return priorityA - priorityB;
  });
}
