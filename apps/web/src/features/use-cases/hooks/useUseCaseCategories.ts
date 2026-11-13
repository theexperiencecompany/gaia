import { useExploreWorkflows } from "@/features/workflows/hooks/useExploreWorkflows";
import type { UseCase } from "@/types/features/workflowTypes";
import { toUseCase } from "../utils/toUseCase";

interface UseUseCaseCategoriesOptions {
  /** Explore workflows supplied by the caller; when absent or empty the store's are fetched. */
  exploreWorkflows?: UseCase[];
  hideAllCategory: boolean;
  hideUserWorkflows: boolean;
}

/**
 * The use cases the section renders plus the ordered category chips derived
 * from them: "all" (optional), "featured", "workflows" (the user's own,
 * optional), then every remaining category found in the data, sorted.
 */
export function useUseCaseCategories({
  exploreWorkflows: propExploreWorkflows,
  hideAllCategory,
  hideUserWorkflows,
}: UseUseCaseCategoriesOptions) {
  // Fetch explore workflows from centralized store (skip if provided via props)
  const { workflows: storeExploreWorkflows } = useExploreWorkflows(
    !propExploreWorkflows || propExploreWorkflows.length === 0,
  );

  // Use provided explore workflows or the store's, shaped for the grid
  const exploreWorkflows =
    propExploreWorkflows && propExploreWorkflows.length > 0
      ? propExploreWorkflows
      : storeExploreWorkflows.map(toUseCase);

  // Generate categories dynamically from the actual data
  const dynamicCategories = Array.from(
    new Set(exploreWorkflows.flatMap((uc) => uc.categories || [])),
  ).toSorted((a, b) => a.localeCompare(b));

  const allCategories = [
    ...(hideAllCategory ? [] : ["all"]),
    "featured",
    ...(hideUserWorkflows ? [] : ["workflows"]),
    ...dynamicCategories.filter((cat) => cat !== "featured"),
  ];

  return { exploreWorkflows, allCategories };
}
