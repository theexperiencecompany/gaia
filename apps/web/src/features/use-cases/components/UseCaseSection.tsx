import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { StarAward01Icon, WorkflowCircle03Icon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import Link from "next/link";
import { useState } from "react";
import { ChevronUp } from "@/components/shared/icons";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import { useWorkflows } from "@/features/workflows/hooks/useWorkflows";
import type { UseCase } from "@/types/features/workflowTypes";
import { useScrollContainer } from "../hooks/useScrollContainer";
import { useUseCaseCategories } from "../hooks/useUseCaseCategories";

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

// Unique step categories, in order — one pass (dedupe via Set) instead of a
// map→filter chain.
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

interface UseCaseSectionOptions {
  /** Hide the "Your Workflows" category and skip fetching the user's workflows. */
  hideUserWorkflows?: boolean;
  /** Center the category chip row horizontally. */
  centered?: boolean;
  /** Render card descriptions as tooltips instead of inline text. */
  showDescriptionAsTooltip?: boolean;
  /** Enable the blur backdrop effect on cards. */
  useBlurEffect?: boolean;
  /** Disable horizontal auto-centering of the workflow grids. */
  disableCentering?: boolean;
  /** Remove the max-width cap from the workflow grids. */
  noMaxWidth?: boolean;
  /** Hide the "All" category chip. */
  hideAllCategory?: boolean;
}

export default function UseCaseSection({
  dummySectionRef,
  exploreWorkflows: propExploreWorkflows,
  setShowUseCases,
  slicePerTab,
  rows,
  columns = 4,
  scroller,
  options = {},
}: {
  dummySectionRef: React.RefObject<HTMLDivElement | null>;
  exploreWorkflows?: UseCase[];
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
  slicePerTab?: number;
  rows?: number;
  columns?: number;
  /** Pass null to skip scroll container detection (e.g. on landing page where window is the scroller). */
  scroller?: HTMLElement | null;
  /** Display/layout toggles — all optional; see {@link UseCaseSectionOptions}. */
  options?: UseCaseSectionOptions;
}) {
  const {
    hideUserWorkflows = false,
    centered = true,
    showDescriptionAsTooltip,
    useBlurEffect,
    disableCentering = false,
    noMaxWidth = false,
    hideAllCategory = false,
  } = options;
  const [selectedCategory, setSelectedCategory] = useState<string | null>(
    "featured",
  );

  // Fetch user workflows if needed
  const { workflows, isLoading: isLoadingWorkflows } = useWorkflows(
    !hideUserWorkflows,
  );

  const { exploreWorkflows, allCategories } = useUseCaseCategories({
    exploreWorkflows: propExploreWorkflows,
    hideAllCategory,
    hideUserWorkflows,
  });

  const getScrollContainer = useScrollContainer(dummySectionRef, scroller);

  const filteredUseCases = filterUseCases(exploreWorkflows, selectedCategory);

  const handleCategoryClick = (category: string) => {
    const scrollContainer = getScrollContainer();
    const useWindowScroll = scrollContainer === null;

    if (selectedCategory !== category) {
      setSelectedCategory(category);
      // Small delay to let state update, then bring the section into view
      setTimeout(() => {
        if (!dummySectionRef.current) return;
        scrollSectionIntoView(
          dummySectionRef.current,
          scrollContainer,
          useWindowScroll,
          category,
        );
      }, 50);
      return;
    }
    if (category === "featured") {
      // Featured clicked again: briefly unselect then reselect for feedback
      setSelectedCategory(null);
      setTimeout(() => setSelectedCategory("featured"), 100);
      return;
    }
    // Any other category unselects back to featured, at the top
    setSelectedCategory("featured");
    scrollToTop(scrollContainer, useWindowScroll);
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
            <UseCasesGrid
              key={selectedCategory}
              useCases={filteredUseCases}
              slicePerTab={slicePerTab}
              rows={rows}
              columns={columns}
              disableCentering={disableCentering}
              noMaxWidth={noMaxWidth}
              setShowUseCases={setShowUseCases}
              showDescriptionAsTooltip={showDescriptionAsTooltip}
              useBlurEffect={useBlurEffect}
            />
          )}

        {/* Render User Workflows */}
        {selectedCategory === "workflows" &&
          !isLoadingWorkflows &&
          workflows.length > 0 && (
            <UserWorkflowsGrid
              workflows={workflows}
              columns={columns}
              disableCentering={disableCentering}
              noMaxWidth={noMaxWidth}
              setShowUseCases={setShowUseCases}
              showDescriptionAsTooltip={showDescriptionAsTooltip}
              useBlurEffect={useBlurEffect}
            />
          )}
      </AnimatePresence>

      <UseCaseEmptyStates
        filteredUseCasesLength={filteredUseCases.length}
        selectedCategory={selectedCategory}
        isLoadingWorkflows={isLoadingWorkflows}
        workflowsLength={workflows.length}
      />
    </div>
  );
}

function gridClassName(opts: {
  disableCentering: boolean;
  noMaxWidth: boolean;
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
}): string {
  return `${opts.disableCentering ? "" : "mx-auto"} grid ${opts.noMaxWidth ? "" : opts.setShowUseCases ? "max-w-5xl" : "max-w-7xl"} grid-cols-1 gap-6 sm:grid-cols-2`;
}

interface UseCasesGridProps {
  useCases: UseCase[];
  slicePerTab?: number;
  rows?: number;
  columns: number;
  disableCentering?: boolean;
  noMaxWidth?: boolean;
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
  showDescriptionAsTooltip?: boolean;
  useBlurEffect?: boolean;
}

function UseCasesGrid({
  useCases,
  slicePerTab,
  rows,
  columns,
  disableCentering = false,
  noMaxWidth = false,
  setShowUseCases,
  showDescriptionAsTooltip,
  useBlurEffect,
}: UseCasesGridProps) {
  const sliced = sliceUseCases(useCases, slicePerTab, rows, columns);
  return (
    <m.div
      className={`${gridClassName({ disableCentering, noMaxWidth, setShowUseCases })} ${COLUMN_CLASSES[columns] ?? COLUMN_CLASSES[4]}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {sliced.map((useCase: UseCase, index: number) => (
        <m.div
          key={useCase.published_id}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.3,
            delay: index * 0.05,
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
            href={useCase.slug ? `/use-cases/${useCase.slug}` : undefined}
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
              useCase.action_type === "prompt" ? "insert-prompt" : "create"
            }
          />
        </m.div>
      ))}
    </m.div>
  );
}

interface UserWorkflowsGridProps {
  workflows: Workflow[];
  columns: number;
  disableCentering?: boolean;
  noMaxWidth?: boolean;
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
  showDescriptionAsTooltip?: boolean;
  useBlurEffect?: boolean;
}

function UserWorkflowsGrid({
  workflows,
  columns,
  disableCentering = false,
  noMaxWidth = false,
  setShowUseCases,
  showDescriptionAsTooltip,
  useBlurEffect,
}: UserWorkflowsGridProps) {
  return (
    <m.div
      className={`${gridClassName({ disableCentering, noMaxWidth, setShowUseCases })} ${COLUMN_CLASSES[columns] ?? COLUMN_CLASSES[4]}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {workflows.map((workflow: Workflow, index: number) => (
        <m.div
          key={workflow.id}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.3,
            delay: index * 0.05,
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
  );
}

function UseCaseEmptyStates({
  filteredUseCasesLength,
  selectedCategory,
  isLoadingWorkflows,
  workflowsLength,
}: {
  filteredUseCasesLength: number;
  selectedCategory: string | null;
  isLoadingWorkflows: boolean;
  workflowsLength: number;
}) {
  return (
    <>
      {/* Empty states */}
      {filteredUseCasesLength === 0 &&
        selectedCategory !== null &&
        selectedCategory !== "workflows" && (
          <div className="flex h-48 items-center justify-center"></div>
        )}

      {selectedCategory === "workflows" &&
        !isLoadingWorkflows &&
        workflowsLength === 0 && (
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
    </>
  );
}
