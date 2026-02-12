import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { AnimatePresence, motion } from "framer-motion";
import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  ChevronUp,
  StarAward01Icon,
  WorkflowCircle03Icon,
} from "@/components/shared/icons";
import type { UseCase } from "@/features/use-cases/types";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import { useExploreWorkflows, useWorkflows } from "@/features/workflows/hooks";

// Register GSAP plugin
gsap.registerPlugin(ScrollTrigger);

export default function UseCaseSection({
  dummySectionRef,
  hideUserWorkflows = false,
  centered = true,
  exploreWorkflows: propExploreWorkflows,
  setShowUseCases,
  showDescriptionAsTooltip,
  useBlurEffect,
  disableCentering = false,
  slicePerTab,
  hideAllCategory = false,
  rows,
  columns = 4,
}: {
  dummySectionRef: React.RefObject<HTMLDivElement | null>;
  hideUserWorkflows?: boolean;
  centered?: boolean;
  exploreWorkflows?: UseCase[];
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
  showDescriptionAsTooltip?: boolean;
  useBlurEffect?: boolean;
  disableCentering?: boolean;
  slicePerTab?: number;
  hideAllCategory?: boolean;
  rows?: number;
  columns?: number;
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
      integrations:
        w.steps
          ?.map((s) => s.category)
          .filter((v, i, a) => a.indexOf(v) === i) || [],
      categories: w.categories || ["featured"],
      published_id: w.id,
      slug: w.id,
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
  ).sort();

  const allCategories = [
    ...(hideAllCategory ? [] : ["all"]),
    "featured",
    ...(hideUserWorkflows ? [] : ["workflows"]),
    ...dynamicCategories.filter((cat) => cat !== "featured"),
  ];

  // Find scroll container - memoized to prevent effect re-runs
  const getScrollContainer = useCallback(() => {
    let current = dummySectionRef.current?.parentElement;
    while (current) {
      const styles = window.getComputedStyle(current);
      if (styles.overflowY === "auto" || styles.overflowY === "scroll") {
        return current;
      }
      current = current.parentElement;
    }
    return null;
  }, [dummySectionRef]);

  // Simple GSAP ScrollTrigger
  useEffect(() => {
    if (!dummySectionRef.current) return;

    const scrollContainer = getScrollContainer();
    if (!scrollContainer) return;

    const trigger = ScrollTrigger.create({
      trigger: dummySectionRef.current,
      scroller: scrollContainer,
      start: "top 50%",
      end: "bottom-=10 40%",
    });

    return () => trigger.kill();
  }, [dummySectionRef, getScrollContainer]);

  const filteredUseCases =
    selectedCategory === null
      ? exploreWorkflows.filter((useCase: UseCase) =>
          useCase.categories?.includes("featured"),
        ) // Show featured when null (fallback)
      : selectedCategory === "all"
        ? exploreWorkflows
        : exploreWorkflows.filter((useCase: UseCase) =>
            useCase.categories?.includes(selectedCategory),
          );

  const handleCategoryClick = (category: string) => {
    const wasSelected = selectedCategory === category;
    const scrollContainer = getScrollContainer();

    if (!scrollContainer) return;

    if (wasSelected) {
      // Unselecting: for featured, go back to default, for others scroll to top and reset to featured
      if (category === "featured") {
        // If featured is clicked again, briefly unselect then reselect to show visual feedback
        setSelectedCategory(null);
        setTimeout(() => setSelectedCategory("featured"), 100);
      } else {
        // For other categories, unselect and go back to featured as default
        setSelectedCategory("featured");
        gsap.to(scrollContainer, {
          scrollTop: 0,
          duration: 0.5,
          ease: "power2.out",
        });
      }
    } else {
      // Selecting: only scroll if we need to bring the section into view
      setSelectedCategory(category);

      // Small delay to let state update
      setTimeout(() => {
        if (!dummySectionRef.current) return;

        const sectionRect = dummySectionRef.current.getBoundingClientRect();
        const containerRect = scrollContainer.getBoundingClientRect();
        const currentScrollTop = scrollContainer.scrollTop;

        // Only scroll if the section is not fully visible or if we need to scroll down
        const isSectionFullyVisible =
          sectionRect.top >= containerRect.top &&
          sectionRect.bottom <= containerRect.bottom;

        // For workflows category, don't scroll at all to prevent the scroll-up issue
        if (category === "workflows") {
          return;
        }

        // For other categories, only scroll if section is not fully visible
        if (!isSectionFullyVisible) {
          const targetScrollTop =
            currentScrollTop +
            (sectionRect.bottom - containerRect.bottom) +
            100;

          gsap.to(scrollContainer, {
            scrollTop: Math.max(0, targetScrollTop),
            duration: 0.5,
            ease: "power2.out",
          });
        }
      }, 50);
    }
  };

  // Cleanup
  useEffect(() => {
    return () => {
      ScrollTrigger.getAll().forEach((trigger) => trigger.kill());
    };
  }, []);

  return (
    <div className="w-full" ref={dummySectionRef}>
      <div
        className={`mb-6 flex flex-wrap ${setShowUseCases ? "max-w-5xl mx-auto" : ""} ${centered ? "justify-center" : ""} items-center gap-2`}
      >
        {allCategories.map((category, index) => (
          <motion.div
            key={category as string}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.3,
              delay: index * 0.05,
              ease: "easeOut",
            }}
          >
            <Chip
              variant={selectedCategory === category ? "solid" : "flat"}
              color={selectedCategory === category ? "primary" : "default"}
              className={`cursor-pointer capitalize ${selectedCategory === category ? "" : "bg-white/5! text-foreground-500"} font-light! backdrop-blur-2xl!`}
              size="lg"
              startContent={
                category === "featured" ? (
                  <StarAward01Icon width={18} height={18} />
                ) : category === "workflows" ? (
                  <WorkflowCircle03Icon width={18} height={18} />
                ) : undefined
              }
              onClick={() => handleCategoryClick(category as string)}
            >
              {category === "all"
                ? "All"
                : category === "featured"
                  ? "Featured"
                  : category === "workflows"
                    ? "Your Workflows"
                    : (category as string)}
            </Chip>
          </motion.div>
        ))}

        {setShowUseCases && (
          <motion.div
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
          </motion.div>
        )}
      </div>

      <AnimatePresence mode="wait">
        {/* Render Use Cases */}
        {filteredUseCases.length > 0 &&
          selectedCategory !== null &&
          selectedCategory !== "workflows" && (
            <motion.div
              key={selectedCategory}
              className={`${disableCentering ? "" : "mx-auto"} grid ${setShowUseCases ? "max-w-5xl" : "max-w-7xl"} grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-${columns} xl:grid-cols-${columns}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
            >
              {(slicePerTab || rows
                ? filteredUseCases.slice(
                    0,
                    slicePerTab || (rows ? rows * columns : undefined),
                  )
                : filteredUseCases
              ).map((useCase: UseCase, index: number) => (
                <motion.div
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
                    steps={useCase.steps}
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
                </motion.div>
              ))}
            </motion.div>
          )}

        {/* Render User Workflows */}
        {selectedCategory === "workflows" &&
          !isLoadingWorkflows &&
          workflows.length > 0 && (
            <motion.div
              key="workflows"
              className={`${disableCentering ? "" : "mx-auto"} grid ${setShowUseCases ? "max-w-5xl" : "max-w-7xl"}  grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-${columns} xl:grid-cols-${columns}`}
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -20 }}
              transition={{ duration: 0.3, ease: "easeOut" }}
            >
              {workflows
                // .slice(0, 8)
                .map((workflow: Workflow, index: number) => (
                  <motion.div
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
                  </motion.div>
                ))}
            </motion.div>
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
