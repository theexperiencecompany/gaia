import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { ShuffleIcon } from "@icons";
import { useReducedMotion } from "motion/react";
import * as m from "motion/react-m";
import type React from "react";
import { memo, useCallback, useEffect, useMemo, useState } from "react";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import WorkflowModal from "@/features/workflows/components/WorkflowModal";
import { useExploreWorkflows } from "@/features/workflows/hooks/useExploreWorkflows";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";

const shuffleArray = <T,>(array: T[]): T[] => {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

interface SuggestionCardProps {
  workflow: CommunityWorkflow;
  index: number;
  onCardClick: (workflow: CommunityWorkflow) => void;
}

const SuggestionCard = memo(function SuggestionCard({
  workflow,
  index,
  onCardClick,
}: SuggestionCardProps) {
  const shouldReduceMotion = useReducedMotion();

  const handleClick = useCallback(() => {
    onCardClick(workflow);
  }, [onCardClick, workflow]);

  return (
    <m.div
      initial={{ opacity: 0, y: shouldReduceMotion ? 0 : 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: shouldReduceMotion ? 0 : 0.3,
        delay: shouldReduceMotion ? 0 : index * 0.05,
        ease: "easeOut",
      }}
    >
      <UnifiedWorkflowCard
        communityWorkflow={workflow}
        variant="suggestion"
        showExecutions={true}
        actionButtonLabel="Try"
        onCardClick={handleClick}
        primaryAction="none"
      />
    </m.div>
  );
});

export const ChatSuggestions: React.FC = () => {
  const { workflows: allWorkflows } = useExploreWorkflows();
  const [currentSuggestions, setCurrentSuggestions] = useState<
    CommunityWorkflow[]
  >([]);
  const [selectedWorkflow, setSelectedWorkflow] =
    useState<CommunityWorkflow | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Clear selectedWorkflow only after the modal's exit animation finishes —
  // dropping it synchronously on close unmounts the modal mid-animation and
  // produces a flash. The 250ms matches HeroUI's modal exit transition.
  useEffect(() => {
    if (isModalOpen || !selectedWorkflow) return;
    const timer = window.setTimeout(() => setSelectedWorkflow(null), 250);
    return () => window.clearTimeout(timer);
  }, [isModalOpen, selectedWorkflow]);

  // Filter for only featured workflows
  const featuredWorkflows = useMemo(
    () =>
      allWorkflows.filter((workflow) =>
        workflow.categories?.includes("featured"),
      ),
    [allWorkflows],
  );

  // Set initial suggestions when featured workflows are available
  useEffect(() => {
    if (featuredWorkflows.length > 0 && currentSuggestions.length === 0) {
      const initialSuggestions = shuffleArray(featuredWorkflows).slice(0, 3);
      setCurrentSuggestions(initialSuggestions);
    }
  }, [featuredWorkflows, currentSuggestions.length]);

  const handleShuffle = useCallback(() => {
    trackEvent(ANALYTICS_EVENTS.CHAT_SUGGESTION_SHUFFLED, {
      current_suggestion_ids: currentSuggestions.map((w) => w.id),
    });
    const currentIds = new Set(currentSuggestions.map((w) => w.id));

    // Filter out currently displayed workflows
    const availableWorkflows = featuredWorkflows.filter(
      (w) => !currentIds.has(w.id),
    );

    // If we don't have enough different workflows, use all workflows
    if (availableWorkflows.length < 3) {
      const newSuggestions = shuffleArray(featuredWorkflows).slice(0, 3);
      setCurrentSuggestions(newSuggestions);
    } else {
      const newSuggestions = shuffleArray(availableWorkflows).slice(0, 3);
      setCurrentSuggestions(newSuggestions);
    }
  }, [currentSuggestions, featuredWorkflows]);

  const handleSuggestionClick = useCallback((workflow: CommunityWorkflow) => {
    setSelectedWorkflow(workflow);
    setIsModalOpen(true);
  }, []);

  const draftData = useMemo(() => {
    if (!selectedWorkflow) return null;
    return {
      suggested_title: selectedWorkflow.title,
      suggested_description: selectedWorkflow.description,
      prompt: selectedWorkflow.prompt || selectedWorkflow.description,
      trigger_type: "manual" as const,
    };
  }, [selectedWorkflow]);

  return (
    <section
      className="w-full max-w-4xl mt-10"
      aria-label="Workflow suggestions"
    >
      <div className="mb-2 flex w-full items-end justify-between px-1 text-zinc-300">
        <h2 className="text-sm font-light">Suggestions</h2>
        <Tooltip content="Shuffle suggestions" placement="top">
          <Button
            isIconOnly
            size="sm"
            variant="light"
            aria-label="Shuffle suggestions"
            onPress={handleShuffle}
          >
            <ShuffleIcon width={16} height={16} className="text-zinc-300" />
          </Button>
        </Tooltip>
      </div>

      {currentSuggestions.length === 0 && (
        <div className="text-sm text-zinc-300 flex items-center justify-center py-8">
          No Suggestions found
        </div>
      )}

      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 md:grid-cols-3">
        {currentSuggestions.map((workflow, index) => (
          <SuggestionCard
            key={workflow.id}
            workflow={workflow}
            index={index}
            onCardClick={handleSuggestionClick}
          />
        ))}
      </div>

      {selectedWorkflow && draftData && (
        <WorkflowModal
          isOpen={isModalOpen}
          onOpenChange={setIsModalOpen}
          mode="create"
          draftData={draftData}
          predefinedSteps={selectedWorkflow.steps}
          createAndSend
        />
      )}
    </section>
  );
};

ChatSuggestions.displayName = "ChatSuggestions";
