import { Button } from "@heroui/button";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useCallback, useRef, useState } from "react";
import { ChevronUp } from "@/components/shared/icons";
import { useExploreWorkflows } from "@/features/workflows/hooks/useExploreWorkflows";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";
import type { UseCase } from "@/types/features/workflowTypes";
import { CategoryChip } from "./CategoryChip";
import { UseCaseEmptyStates } from "./UseCaseEmptyStates";
import { UseCaseGrid } from "./UseCaseGrid";
import {
  filterUseCases,
  scrollSectionIntoView,
  scrollToTop,
  sliceUseCases,
} from "./UseCaseSection.helpers";
import { WorkflowsGrid } from "./WorkflowsGrid";

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
  scroller?: HTMLElement | null;
}) {
  const [selectedCategory, setSelectedCategory] = useState<string | null>(
    "featured",
  );

  const { workflows, isLoading: isLoadingWorkflows } = useWorkflows(
    !hideUserWorkflows,
  );

  const { workflows: storeExploreWorkflows } = useExploreWorkflows(
    !propExploreWorkflows || propExploreWorkflows.length === 0,
  );

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
      integrations: Array.from(new Set(w.steps?.map((s) => s.category) ?? [])),
      categories: w.categories || ["featured"],
      published_id: w.id,
      slug: w.slug ?? undefined,
      steps: w.steps,
      creator: w.creator,
      total_executions: w.total_executions || 0,
    }),
  );

  const exploreWorkflows =
    propExploreWorkflows && propExploreWorkflows.length > 0
      ? propExploreWorkflows
      : convertedExploreWorkflows;

  const dynamicCategories = Array.from(
    new Set(exploreWorkflows.flatMap((uc) => uc.categories || [])),
  ).toSorted();

  const allCategories = [
    ...(hideAllCategory ? [] : ["all"]),
    "featured",
    ...(hideUserWorkflows ? [] : ["workflows"]),
    ...dynamicCategories.filter((cat) => cat !== "featured"),
  ];

  const scrollContainerCache = useRef<HTMLElement | null | undefined>(
    undefined,
  );

  const getScrollContainer = useCallback((): HTMLElement | null => {
    if (scroller !== undefined) return scroller;

    if (scrollContainerCache.current !== undefined) {
      return scrollContainerCache.current;
    }

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
      if (category === "featured") {
        setSelectedCategory(null);
        setTimeout(() => setSelectedCategory("featured"), 100);
      } else {
        setSelectedCategory("featured");
        scrollToTop(scrollContainer, useWindowScroll);
      }
    } else {
      setSelectedCategory(category);
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

  const slicedUseCases = sliceUseCases(
    filteredUseCases,
    slicePerTab,
    rows,
    columns,
  );

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
              className="text-zinc-300"
            >
              <ChevronUp />
            </Button>
          </m.div>
        )}
      </div>

      <AnimatePresence mode="wait">
        {filteredUseCases.length > 0 &&
          selectedCategory !== null &&
          selectedCategory !== "workflows" && (
            <UseCaseGrid
              useCases={slicedUseCases}
              category={selectedCategory}
              disableCentering={disableCentering}
              noMaxWidth={noMaxWidth}
              setShowUseCases={setShowUseCases}
              showDescriptionAsTooltip={showDescriptionAsTooltip}
              useBlurEffect={useBlurEffect}
              columns={columns}
            />
          )}

        {selectedCategory === "workflows" &&
          !isLoadingWorkflows &&
          workflows.length > 0 && (
            <WorkflowsGrid
              workflows={workflows}
              disableCentering={disableCentering}
              noMaxWidth={noMaxWidth}
              setShowUseCases={setShowUseCases}
              showDescriptionAsTooltip={showDescriptionAsTooltip}
              useBlurEffect={useBlurEffect}
              columns={columns}
            />
          )}
      </AnimatePresence>

      <UseCaseEmptyStates
        filteredUseCasesLength={filteredUseCases.length}
        selectedCategory={selectedCategory}
        workflowsLength={workflows.length}
        isLoadingWorkflows={isLoadingWorkflows}
      />
    </div>
  );
}
