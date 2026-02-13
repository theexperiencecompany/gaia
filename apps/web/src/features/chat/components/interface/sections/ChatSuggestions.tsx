import { Button } from "@heroui/button";
import { UndoIcon } from "@icons";
import { m } from "motion/react";
import type React from "react";
import { useCallback, useMemo, useState } from "react";
import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import { useExploreWorkflows } from "@/features/workflows/hooks";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useComposerTextActions } from "@/stores/composerStore";
import type { CommunityWorkflow } from "@/types/features/workflowTypes";

const shuffleArray = <T,>(array: T[]): T[] => {
  const shuffled = [...array];
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  return shuffled;
};

interface ChatSuggestionsProps {
  onSubmitSuggestion?: () => void;
}

export const ChatSuggestions: React.FC<ChatSuggestionsProps> = () => {
  const { workflows: allWorkflows } = useExploreWorkflows();
  const [currentSuggestions, setCurrentSuggestions] = useState<
    CommunityWorkflow[]
  >([]);
  const { clearInputText } = useComposerTextActions();
  const { setContextualLoading } = useLoadingText();

  // Filter for only featured workflows
  const featuredWorkflows = useMemo(
    () =>
      allWorkflows.filter((workflow) =>
        workflow.categories?.includes("featured"),
      ),
    [allWorkflows],
  );

  // Set initial suggestions when featured workflows are available
  useMemo(() => {
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

  return (
    <div className="w-full max-w-4xl mt-10">
      <div className="mb-2 flex w-full items-end justify-between px-1 text-zinc-400">
        <span className="text-sm font-light">Suggestions</span>
        <Button isIconOnly size="sm" variant="light" onPress={handleShuffle}>
          <UndoIcon width={16} height={16} className="text-zinc-400" />
        </Button>
      </div>

      {currentSuggestions.length === 0 && (
        <div className="text-sm text-zinc-400 flex items-center justify-center py-8">
          No Suggestions found
        </div>
      )}

      <m.div
        className="grid w-full grid-cols-3 gap-4"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
      >
        {currentSuggestions.map((workflow, index) => (
          <m.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.3,
              delay: index * 0.05,
              ease: "easeOut",
            }}
            key={workflow.id}
          >
            <UnifiedWorkflowCard
              communityWorkflow={workflow}
              variant="suggestion"
              showExecutions={true}
              showDescriptionAsTooltip={true}
              actionButtonLabel="Try"
              onActionComplete={() => {
                setContextualLoading(true, workflow.title);
                clearInputText();
              }}
            />
          </m.div>
        ))}
      </m.div>
    </div>
  );
};

ChatSuggestions.displayName = "ChatSuggestions";
