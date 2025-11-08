import { Button } from "@heroui/button";
import { ShuffleIcon } from "lucide-react";
import React, { useCallback, useState } from "react";

import { useLoadingText } from "@/features/chat/hooks/useLoadingText";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useSendMessage } from "@/hooks/useSendMessage";
import { posthog } from "@/lib/posthog";
import { useComposerTextActions } from "@/stores/composerStore";

interface ChatSuggestion {
  id: number;
  icon: React.ReactNode;
  text: string;
  category: string;
}

interface ChatSuggestionsProps {
  onSubmitSuggestion?: () => void;
}

const getAllSuggestions = (): ChatSuggestion[] => [
  // Default suggestions shown on page load
  {
    id: 1,
    icon: getToolCategoryIcon("gmail", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Check my unread emails",
    category: "gmail",
  },
  {
    id: 2,
    icon: getToolCategoryIcon("gmail", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Compose a new email",
    category: "gmail",
  },
  {
    id: 3,
    icon: getToolCategoryIcon("calendar", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "What's on my calendar today?",
    category: "calendar",
  },
  {
    id: 4,
    icon: getToolCategoryIcon("calendar", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Schedule a new meeting",
    category: "calendar",
  },
  // Additional suggestions for shuffle
  {
    id: 5,
    icon: getToolCategoryIcon("gmail", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Search emails by keyword",
    category: "gmail",
  },
  {
    id: 6,
    icon: getToolCategoryIcon("calendar", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Find free time this week",
    category: "calendar",
  },
  {
    id: 7,
    icon: getToolCategoryIcon("notion", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Create a new document",
    category: "notion",
  },
  {
    id: 8,
    icon: getToolCategoryIcon("notion", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Take notes from meeting",
    category: "notion",
  },
  {
    id: 9,
    icon: getToolCategoryIcon("productivity", { showBackground: true }),
    text: "Show me my todo list",
    category: "productivity",
  },
  {
    id: 10,
    icon: getToolCategoryIcon("productivity", { showBackground: true }),
    text: "Plan my tasks for today",
    category: "productivity",
  },
  {
    id: 11,
    icon: getToolCategoryIcon("documents", { showBackground: true }),
    text: "Write a project summary",
    category: "documents",
  },
  {
    id: 12,
    icon: getToolCategoryIcon("documents", { showBackground: true }),
    text: "Draft a business proposal",
    category: "documents",
  },
  {
    id: 13,
    icon: getToolCategoryIcon("search", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "Research current market trends",
    category: "search",
  },
  {
    id: 14,
    icon: getToolCategoryIcon("weather", {
      showBackground: false,
      width: 25,
      height: 25,
    }),
    text: "What's the weather today?",
    category: "weather",
  },
  {
    id: 15,
    icon: getToolCategoryIcon("creative", { showBackground: true }),
    text: "Generate an image for my project",
    category: "creative",
  },
  {
    id: 16,
    icon: getToolCategoryIcon("memory", { showBackground: true }),
    text: "Remember this for later",
    category: "memory",
  },
];

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
  const [currentSuggestions, setCurrentSuggestions] = useState(
    () => getAllSuggestions().slice(0, 4), // Show first 4 items on load (default suggestions)
  );
  const { clearInputText } = useComposerTextActions();
  const sendMessage = useSendMessage();
  const { setContextualLoading } = useLoadingText();

  const handleShuffle = useCallback(() => {
    posthog.capture("chat:suggestion_shuffled", {
      current_suggestion_ids: currentSuggestions.map((s) => s.id),
    });

    const allSuggestions = getAllSuggestions();
    const currentIds = new Set(currentSuggestions.map((s) => s.id));

    // Filter out currently displayed suggestions
    const availableSuggestions = allSuggestions.filter(
      (s) => !currentIds.has(s.id),
    );

    // If we don't have enough different suggestions, use all suggestions
    if (availableSuggestions.length < 4) {
      const newSuggestions = shuffleArray(allSuggestions).slice(0, 4);
      setCurrentSuggestions(newSuggestions);
    } else {
      const newSuggestions = shuffleArray(availableSuggestions).slice(0, 4);
      setCurrentSuggestions(newSuggestions);
    }
  }, [currentSuggestions]);

  const handleSuggestionClick = useCallback(
    async (suggestion: ChatSuggestion) => {
      // Track suggestion click
      posthog.capture("chat:suggestion_clicked", {
        suggestion_id: suggestion.id,
        suggestion_text: suggestion.text,
        suggestion_category: suggestion.category,
      });

      // Set loading state with contextual message
      setContextualLoading(true, suggestion.text);

      // Send message directly with the suggestion text
      await sendMessage(suggestion.text);

      // Clear the input text after sending (mimicking Composer behavior)
      clearInputText();
    },
    [sendMessage, setContextualLoading, clearInputText],
  );

  return (
    <div className="w-full max-w-5xl">
      <div className="mb-2 flex w-full items-end justify-between px-1 text-zinc-400">
        <span className="text-sm font-light">Suggestions</span>
        <Button isIconOnly size="sm" variant="light" onPress={handleShuffle}>
          <ShuffleIcon width={16} height={16} className="text-zinc-400" />
        </Button>
      </div>
      <div className="grid w-full grid-cols-4 gap-4">
        {currentSuggestions.map((suggestion) => {
          return (
            <div
              key={suggestion.id}
              className="flex min-h-20 w-full cursor-pointer flex-col justify-start gap-2 rounded-2xl bg-zinc-800/70 p-4 text-zinc-400 transition-colors hover:bg-zinc-700/70"
              onClick={() => handleSuggestionClick(suggestion)}
            >
              <div className="h-6">
                <div className="flex aspect-square h-fit w-fit items-center justify-center">
                  {suggestion.icon}
                </div>
              </div>
              <div className="text-sm">{suggestion.text}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

ChatSuggestions.displayName = "ChatSuggestions";
