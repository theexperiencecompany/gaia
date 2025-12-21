/**
 * Integration category utilities
 *
 * Categories are derived dynamically from backend integrations data.
 * This file only provides display labels and utility functions.
 */

/**
 * Display labels for category IDs
 * These are presentation-only - the category IDs themselves come from backend
 */
export const CATEGORY_LABELS: Record<string, string> = {
  all: "All",
  productivity: "Productivity",
  developer: "Developer",
  business: "Business",
  social: "Social Media",
  communication: "Communication",
};

/**
 * Get display label for a category ID
 */
export function getCategoryLabel(categoryId: string): string {
  return CATEGORY_LABELS[categoryId] ?? categoryId;
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
export const CATEGORY_DISPLAY_PRIORITY: Record<string, number> = {
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
  return categories.sort((a, b) => {
    const priorityA = CATEGORY_DISPLAY_PRIORITY[a] ?? 100;
    const priorityB = CATEGORY_DISPLAY_PRIORITY[b] ?? 100;
    return priorityA - priorityB;
  });
}
