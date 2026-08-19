import type { UseCase } from "@/types/features/workflowTypes";

export function scrollToTop(
  scrollContainer: HTMLElement | null,
  useWindowScroll: boolean,
): void {
  if (useWindowScroll) {
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (scrollContainer) {
    scrollContainer.scrollTo({ top: 0, behavior: "smooth" });
  }
}

export function scrollSectionIntoView(
  section: HTMLElement,
  scrollContainer: HTMLElement | null,
  useWindowScroll: boolean,
  category: string,
): void {
  const sectionRect = section.getBoundingClientRect();
  const containerRect = useWindowScroll
    ? { top: 0, bottom: window.innerHeight }
    : scrollContainer
      ? scrollContainer.getBoundingClientRect()
      : null;
  if (!containerRect) return;

  const currentScrollTop = useWindowScroll
    ? window.scrollY
    : (scrollContainer?.scrollTop ?? 0);

  const isSectionFullyVisible =
    sectionRect.top >= containerRect.top &&
    sectionRect.bottom <= containerRect.bottom;

  if (category === "workflows") return;

  if (isSectionFullyVisible) return;

  const top = Math.max(
    0,
    currentScrollTop + (sectionRect.bottom - containerRect.bottom) + 100,
  );

  if (useWindowScroll) {
    window.scrollTo({ top, behavior: "smooth" });
  } else if (scrollContainer) {
    scrollContainer.scrollTo({ top, behavior: "smooth" });
  }
}

export function filterUseCases(
  exploreWorkflows: UseCase[],
  selectedCategory: string | null,
): UseCase[] {
  if (selectedCategory === null) {
    return exploreWorkflows.filter((useCase) =>
      useCase.categories?.includes("featured"),
    );
  }
  if (selectedCategory === "all") {
    return exploreWorkflows;
  }
  return exploreWorkflows.filter((useCase) =>
    useCase.categories?.includes(selectedCategory),
  );
}

export const COLUMN_CLASSES: Record<number, string> = {
  2: "lg:grid-cols-2 xl:grid-cols-2",
  3: "lg:grid-cols-3 xl:grid-cols-3",
  4: "lg:grid-cols-4 xl:grid-cols-4",
};

export function sliceUseCases(
  useCases: UseCase[],
  slicePerTab: number | undefined,
  rows: number | undefined,
  columns: number,
): UseCase[] {
  if (!slicePerTab && !rows) return useCases;
  return useCases.slice(0, slicePerTab || (rows ? rows * columns : undefined));
}
