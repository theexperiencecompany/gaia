import type { UseCase } from "@/types/features/workflowTypes";

/** A workflow page needs at least this much prose to deserve indexing. */
export const MIN_INDEXABLE_DESCRIPTION_LENGTH = 80;
/** ...and enough steps to be a real workflow, not a stub. */
export const MIN_INDEXABLE_STEPS = 2;

/**
 * Quality gate for /use-cases/[slug] indexing. UGC workflow pages render
 * only the title, description, and step chips — a one-line community
 * workflow is a thin page that drags the site-wide quality signal down.
 * Thin pages stay reachable (follow) but out of the index.
 */
export function isIndexableUseCase(useCase: UseCase): boolean {
  const description = (
    useCase.detailed_description ||
    useCase.description ||
    ""
  ).trim();
  return (
    description.length >= MIN_INDEXABLE_DESCRIPTION_LENGTH &&
    (useCase.steps?.length ?? 0) >= MIN_INDEXABLE_STEPS
  );
}

/**
 * Sitemap variant for list-endpoint entries where only the description is
 * available. Used to keep thin community workflows out of the sitemap.
 */
export function isIndexableWorkflowListing(description?: string | null): boolean {
  return (description ?? "").trim().length >= MIN_INDEXABLE_DESCRIPTION_LENGTH;
}
