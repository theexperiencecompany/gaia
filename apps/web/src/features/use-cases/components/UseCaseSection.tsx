import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { StarAward01Icon, WorkflowCircle03Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import { ChevronUp } from "@/components/shared/icons";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import { useExploreWorkflows } from "@/features/workflows/hooks/useExploreWorkflows";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";
import type { UseCase } from "@/types/features/workflowTypes";

// Smoothly scroll the given scroll region (or window) back to the top.
function scrollToTop(
  scrollContainer: HTMLElement | null,
  useWindowScroll: boolean,
): void {
  if (useWindowScroll) {
    window.scrollTo({ top: 0, behavior: "smooth" });
  } else if (scrollContainer) {
    scrollContainer.scrollTo({ top: 0, behavior: "smooth" });
  }
}

// Scroll just enough to bring `section` fully into view within its scroll
// region. No-op for the workflows tab or when the section is already visible.
function scrollSectionIntoView(
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

  // For workflows category, don't scroll at all to prevent the scroll-up issue
  if (category === "workflows") return;

  // For other categories, only scroll if section is not fully visible
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

// Filter the explore workflows down to the selected category (null = featured
// fallback, "all" = everything).
function filterUseCases(
  exploreWorkflows: UseCase[],
  selectedCategory: string | null,
): UseCase[] {
  if (selectedCategory === null) {
    // Show featured when null (fallback)
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

// Static class strings per column count — Tailwind only emits classes it can
// find literally in the source, so these can't be built by interpolation.
const COLUMN_CLASSES: Record<number, string> = {
  2: "lg:grid-cols-2 xl:grid-cols-2",
  3: "lg:grid-cols-3 xl:grid-cols-3",
  4: "lg:grid-cols-4 xl:grid-cols-4",
};

// Cap the rendered use cases by an explicit slice count or a rows x columns grid.
function sliceUseCases(
  useCases: UseCase[],
  slicePerTab: number | undefined,
  rows: number | undefined,
  columns: number,
): UseCase[] {
  if (!slicePerTab && !rows) return useCases;
  return useCases.slice(0, slicePerTab || (rows ? rows * columns : undefined));
}

// A single animated, selectable category filter chip.
function CategoryChip({
  category,
  index,
  isSelected,
  onClick,
}: {
  category: string;
  index: number;
  isSelected: boolean;
  onClick: () => void;
}) {
  return (
    <m.div
      className="shrink-0"
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        delay: index * 0.05,
        ease: "easeOut",
      }}
    >
      <Chip
        variant={isSelected ? "solid" : "flat"}
        color={isSelected ? "primary" : "default"}
        className={`cursor-pointer capitalize ${isSelected ? "" : "bg-white/5! text-foreground-500"} font-light! backdrop-blur-2xl!`}
        size="lg"
        startContent={
          category === "featured" ? (
            <StarAward01Icon width={18} height={18} />
          ) : category === "workflows" ? (
            <WorkflowCircle03Icon width={18} height={18} />
          ) : undefined
        }
        onClick={onClick}
      >
        {category === "all"
          ? "All"
          : category === "featured"
            ? "Featured"
            : category === "workflows"
              ? "Your Workflows"
              : category}
      </Chip>
    </m.div>
  );
}

export default function UseCaseSection({
  dummySectionRef,
  hideUserWorkflows = false,
  centered = true,
  exploreWorkflows: propExploreWorkflows,
  setShowUseCases,
  showDescriptionAsTooltip,
  useBlurEffect,
  disableCentering = false,
  noMaxWidth = false,
  slicePerTab,
  hideAllCategory = false,
  rows,
  columns = 4,
  scroller,
}: {
  dummySectionRef: React.RefObject<HTMLDivElement | null>;
  hideUserWorkflows?: boolean;
  centered?: boolean;
  exploreWorkflows?: UseCase[];
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
  showDescriptionAsTooltip?: boolean;
  useBlurEffect?: boolean;
  disableCentering?: boolean;
  noMaxWidth?: boolean;
  slicePerTab?: number;
  hideAllCategory?: boolean;
  rows?: number;
  columns?: number;
  /** Pass null to skip scroll container detection (e.g. on landing page where window is the scroller). */
  scroller?: HTMLElement | null;
}) {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(
    "featured",
  );

  // Fetch user workflows if needed
  const { workflows, isLoading: isLoadingWorkflows } = useWorkflows(
    !hideUserWorkflows,
  );

  // Fetch explore workflows from centralized store (skip if provided via props)
  const { workflows: storeExploreWorkflows } = useExploreWorkflows(
    !propExploreWorkflows || propExploreWorkflows.length === 0,
  );

  // Convert store workflows to UseCase format
  const convertedExploreWorkflows: UseCase[] = storeExploreWorkflows.map(
    (w) => ({
      title: w.title,
      description: w.description,
      action_type: "workflow" as const,
      icon: w.icon,
      icon_color: w.icon_color,
      system_workflow_key: w.system_workflow_key,
      source_integration: w.source_integration,
      trigger_config: w.trigger_config,
      integrations:
        w.steps
          ?.map((s) => s.category)
          .filter((v, i, a) => a.indexOf(v) === i) || [],
      categories: w.categories || ["featured"],
      published_id: w.id,
      slug: w.slug ?? undefined,
      steps: w.steps,
      creator: w.creator,
      total_executions: w.total_executions || 0,
    }),
  );

  // Use provided explore workflows or converted store workflows
  const exploreWorkflows =
    propExploreWorkflows && propExploreWorkflows.length > 0
      ? propExploreWorkflows
      : convertedExploreWorkflows;

  // Generate categories dynamically from the actual data
  const dynamicCategories = Array.from(
    new Set(exploreWorkflows.flatMap((uc) => uc.categories || [])),
  ).toSorted();

  const allCategories = [
    ...(hideAllCategory ? [] : ["all"]),
    "featured",
    ...(hideUserWorkflows ? [] : ["workflows"]),
    ...dynamicCategories.filter((cat) => cat !== "featured"),
  ];

  // Cache the scroll container to avoid repeated DOM traversals.
  // When `scroller` prop is provided (including null), skip traversal entirely.
  const scrollContainerCache = useRef<HTMLElement | null | undefined>(
    undefined,
  );

  const getScrollContainer = useCallback((): HTMLElement | null => {
    // Explicit prop provided — use it directly (null means window/no container)
    if (scroller !== undefined) return scroller;

    // Return cached result if already resolved
    if (scrollContainerCache.current !== undefined) {
      return scrollContainerCache.current;
    }

    // Walk up the DOM once and cache the result
    let current = dummySectionRef.current?.parentElement;
    while (current) {
      const styles = window.getComputedStyle(current);
      if (styles.overflowY === "auto" || styles.overflowY === "scroll") {
        scrollContainerCache.current = current;
        return current;
      }
      current = current.parentElement;
    }
    scrollContainerCache.current = null;
    return null;
  }, [dummySectionRef, scroller]);

  const filteredUseCases = filterUseCases(exploreWorkflows, selectedCategory);

  const handleCategoryClick = (category: string) => {
    const wasSelected = selectedCategory === category;
    const scrollContainer = getScrollContainer();
    const useWindowScroll = scrollContainer === null;

    if (wasSelected) {
      // Unselecting: for featured, go back to default, for others scroll to top and reset to featured
      if (category === "featured") {
        // If featured is clicked again, briefly unselect then reselect to show visual feedback
        setSelectedCategory(null);
        setTimeout(() => setSelectedCategory("featured"), 100);
      } else {
        // For other categories, unselect and go back to featured as default
        setSelectedCategory("featured");
        scrollToTop(scrollContainer, useWindowScroll);
      }
    } else {
      // Selecting: only scroll if we need to bring the section into view
      setSelectedCategory(category);

      // Small delay to let state update
      setTimeout(() => {
        if (!dummySectionRef.current) return;
        scrollSectionIntoView(
          dummySectionRef.current,
          scrollContainer,
          useWindowScroll,
          category,
        );
      }, 50);
    }
  };

  return (
    <div className="w-full" ref={dummySectionRef}>
      <div
        className={`mb-6 flex flex-nowrap overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden ${setShowUseCases ? "max-w-5xl" : ""} ${centered || setShowUseCases ? "mx-auto w-fit max-w-full" : ""} items-center gap-2`}
      >
        {allCategories.map((category, index) => (
          <CategoryChip
            key={category as string}
            category={category as string}
            index={index}
            isSelected={selectedCategory === category}
            onClick={() => handleCategoryClick(category as string)}
          />
        ))}

        {setShowUseCases && (
          <m.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.3,
              delay: allCategories.length * 0.05,
              ease: "easeOut",
            }}
            className="pl-2"
          >
            <Button
              isIconOnly
              radius="full"
              size="sm"
              variant="flat"
              onPress={() => setShowUseCases(false)}
              className="text-zinc-300 "
            >
              <ChevronUp />
            </Button>
          </m.div>
        )}
      </div>

      <AnimatePresence mode="wait">
        {/* Render Use Cases */}
        {filteredUseCases.length > 0 &&
          selectedCategory !== null &&
          selectedCategory !== "workflows" && (
            <m.div
              key={selectedCategory}
              className={`${disableCentering ? "" : "mx-auto"} grid ${noMaxWidth ? "" : setShowUseCases ? "max-w-5xl" : "max-w-7xl"} grid-cols-1 gap-6 sm:grid-cols-2 ${COLUMN_CLASSES[columns] ?? COLUMN_CLASSES[4]}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
            >
              {sliceUseCases(filteredUseCases, slicePerTab, rows, columns).map(
                (useCase: UseCase, index: number) => (
                  <m.div
                    key={useCase.published_id || index}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.3,
                      delay: index * 0.05, // Stagger animation
                      ease: "easeOut",
                    }}
                  >
                    <UnifiedWorkflowCard
                      showDescriptionAsTooltip={showDescriptionAsTooltip}
                      title={useCase.title || ""}
                      description={useCase.description || ""}
                      actionType={useCase.action_type || "prompt"}
                      prompt={useCase.prompt}
                      slug={useCase.slug}
                      href={
                        useCase.slug ? `/use-cases/${useCase.slug}` : undefined
                      }
                      steps={useCase.steps}
                      icon={useCase.icon}
                      iconColor={useCase.icon_color}
                      systemWorkflowKey={useCase.system_workflow_key}
                      triggerConfig={useCase.trigger_config}
                      creator={useCase.creator}
                      totalExecutions={useCase.total_executions || 0}
                      showExecutions={true}
                      useBlurEffect={useBlurEffect}
                      variant="explore"
                      primaryAction={
                        useCase.action_type === "prompt"
                          ? "insert-prompt"
                          : "create"
                      }
                    />
                  </m.div>
                ),
              )}
            </m.div>
          )}

        {/* Render User Workflows */}
        {selectedCategory === "workflows" &&
          !isLoadingWorkflows &&
          workflows.length > 0 && (
            <m.div
              key="workflows"
              className={`${disableCentering ? "" : "mx-auto"} grid ${noMaxWidth ? "" : setShowUseCases ? "max-w-5xl" : "max-w-7xl"} grid-cols-1 gap-6 sm:grid-cols-2 ${COLUMN_CLASSES[columns] ?? COLUMN_CLASSES[4]}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
            >
              {workflows
                // .slice(0, 8)
                .map((workflow: Workflow, index: number) => (
                  <m.div
                    key={workflow.id}
                    initial={{ opacity: 0, y: 20 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{
                      duration: 0.3,
                      delay: index * 0.05, // Stagger animation
                      ease: "easeOut",
                    }}
                  >
                    <UnifiedWorkflowCard
                      workflow={workflow}
                      showDescriptionAsTooltip={showDescriptionAsTooltip}
                      variant="user"
                      primaryAction="run"
                      useBlurEffect={useBlurEffect}
                    />
                  </m.div>
                ))}
            </m.div>
          )}
      </AnimatePresence>

      {/* Empty states */}
      {filteredUseCases.length === 0 &&
        selectedCategory !== null &&
        selectedCategory !== "workflows" && (
          <div className="flex h-48 items-center justify-center"></div>
        )}

      {selectedCategory === "workflows" &&
        !isLoadingWorkflows &&
        workflows.length === 0 && (
          <div className="flex h-48 items-center justify-center">
            <div className="text-center space-y-1">
              <p className="text-lg text-foreground-600">No workflows found</p>
              <p className="text-sm text-foreground-400 mb-5">
                Create your first workflow to get started
              </p>
              <Link href={"/workflows"}>
                <Button color="primary">Create</Button>
              </Link>
            </div>
          </div>
        )}

      {selectedCategory === "workflows" && isLoadingWorkflows && (
        <div className="flex h-48 items-center justify-center">
          <div className="text-center">
            <p className="text-lg text-foreground-500">Loading workflows...</p>
          </div>
        </div>
      )}
    </div>
  );
}
