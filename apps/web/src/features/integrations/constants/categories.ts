/**
 * Integration category constants and configuration
 */

export const INTEGRATION_CATEGORIES = [
  { id: "all", label: "All" },
  { id: "productivity", label: "Productivity" },
  { id: "developer", label: "Developer" },
  { id: "social", label: "Social Media" },
  { id: "communication", label: "Communication" },
] as const;

export type IntegrationCategoryId =
  (typeof INTEGRATION_CATEGORIES)[number]["id"];

/**
 * Order for displaying category sections when "All" is selected
 */
export const CATEGORY_DISPLAY_ORDER = [
  "productivity",
  "developer",
  "social",
  "communication",
] as const;

/**
 * Get category label by ID
 */
export function getCategoryLabel(categoryId: string): string {
  const category = INTEGRATION_CATEGORIES.find((c) => c.id === categoryId);
  return category?.label ?? categoryId;
}
