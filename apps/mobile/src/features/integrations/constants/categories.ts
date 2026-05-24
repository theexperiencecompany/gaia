/**
 * Centralised display labels and ordering for integration categories.
 * Backend category IDs (snake_case or kebab-case) are normalised here for UI.
 */
export const CATEGORY_LABELS: Record<string, string> = {
  all: "All",
  productivity: "Productivity",
  developer: "Developer",
  communication: "Communication",
  social: "Social",
  analytics: "Analytics",
  finance: "Finance",
  "ai-ml": "AI & ML",
  education: "Education",
  personal: "Personal",
  capabilities: "Capabilities",
  other: "Other",
};

const CATEGORY_ORDER: Record<string, number> = {
  productivity: 0,
  developer: 1,
  communication: 2,
  social: 3,
  analytics: 4,
  finance: 5,
  "ai-ml": 6,
  education: 7,
  personal: 8,
  capabilities: 9,
  other: 99,
};

/**
 * Resolve a human-friendly label for any category ID. Falls back to a
 * Title Case version of the raw ID for unknown categories.
 */
export function getCategoryLabel(categoryId: string): string {
  const known = CATEGORY_LABELS[categoryId];
  if (known) return known;
  return categoryId
    .split(/[_-]/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/**
 * Sort an array of category IDs by the canonical order. Unknown categories
 * are placed before "other" but after every named category.
 */
export function sortCategories(categories: readonly string[]): string[] {
  return [...categories].sort(
    (left, right) =>
      (CATEGORY_ORDER[left] ?? 50) - (CATEGORY_ORDER[right] ?? 50),
  );
}
