import { Button } from "@heroui/button";
import { motion } from "framer-motion";
import type React from "react";
import { useCallback, useEffect, useState } from "react";
import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import { workflowApi } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import { UndoIcon } from "@/icons";
import { posthog } from "@/lib/posthog";
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
  const [allWorkflows, setAllWorkflows] = useState<CommunityWorkflow[]>([]);
  const [currentSuggestions, setCurrentSuggestions] = useState<
    CommunityWorkflow[]
  >([]);
  const { clearInputText } = useComposerTextActions();
  const { setContextualLoading } = useLoadingText();

  // Fetch featured workflows on mount
  useEffect(() => {
    const fetchFeaturedWorkflows = async () => {
      try {
        const response = await workflowApi.getExploreWorkflows(50, 0);

        // Filter for only featured workflows
        const featuredWorkflows = response.workflows.filter((workflow) =>
          workflow.categories?.includes("featured"),
        );

        setAllWorkflows(featuredWorkflows);

        // Set initial 3 random suggestions
        const initialSuggestions = shuffleArray(featuredWorkflows).slice(0, 3);
        setCurrentSuggestions(initialSuggestions);
      } catch (error) {
        console.error("Error fetching featured workflows:", error);
      }
    };

    fetchFeaturedWorkflows();
  }, []);

  const handleShuffle = useCallback(() => {
    posthog.capture("chat:suggestion_shuffled", {
      current_suggestion_ids: currentSuggestions.map((w) => w.id),
    });

    const currentIds = new Set(currentSuggestions.map((w) => w.id));

    // Filter out currently displayed workflows
    const availableWorkflows = allWorkflows.filter(
      (w) => !currentIds.has(w.id),
    );

    // If we don't have enough different workflows, use all workflows
    if (availableWorkflows.length < 3) {
      const newSuggestions = shuffleArray(allWorkflows).slice(0, 3);
      setCurrentSuggestions(newSuggestions);
    } else {
      const newSuggestions = shuffleArray(availableWorkflows).slice(0, 3);
      setCurrentSuggestions(newSuggestions);
    }
  }, [currentSuggestions, allWorkflows]);

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

      <motion.div
        className="grid w-full grid-cols-3 gap-4"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: -20 }}
        transition={{ duration: 0.3, ease: "easeOut" }}
      >
        {currentSuggestions.map((workflow, index) => (
          <motion.div
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
              actionButtonLabel="Try"
              onActionComplete={() => {
                setContextualLoading(true, workflow.title);
                clearInputText();
              }}
            />
          </motion.div>
        ))}
      </motion.div>
    </div>
  );
};

ChatSuggestions.displayName = "ChatSuggestions";
