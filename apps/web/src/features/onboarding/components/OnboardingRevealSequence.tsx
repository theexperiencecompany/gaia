"use client";

import { Button } from "@heroui/button";
import { AnimatePresence, m } from "motion/react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";

import {
  REVEAL_SOCIAL_PROFILES_INTRO,
  REVEAL_TODOS_INTRO,
  REVEAL_TRIAGE_INTRO,
  REVEAL_WRITING_STYLE_INTRO,
} from "../constants/messages";
import type { RevealPhase } from "../hooks/useOnboardingFlow";
import { OnboardingTodoCards } from "./OnboardingTodoCards";
import { SocialProfilesRevealCard } from "./reveal/SocialProfilesRevealCard";
import { TriageRevealCard } from "./reveal/TriageRevealCard";
import { WritingStyleRevealCard } from "./reveal/WritingStyleRevealCard";

const noop = () => {};

const BOT_BUBBLE_DEFAULTS = {
  message_id: "",
  date: undefined,
  pinned: undefined,
  fileIds: undefined,
  fileData: undefined,
  selectedTool: undefined,
  toolCategory: undefined,
  selectedWorkflow: undefined,
  selectedCalendarEvent: undefined,
  isConvoSystemGenerated: undefined,
  follow_up_actions: undefined,
  image_data: undefined,
  memory_data: undefined,
  todo_progress: undefined,
  replyToMessage: undefined,
  setOpenImage: noop,
  setImageData: noop,
  disableActions: true,
} as const;

interface OnboardingRevealSequenceProps {
  revealPhase: RevealPhase;
  writingStyle: { style_summary: string; example?: string } | null;
  profession: string;
  socialProfiles: Array<{ platform: string; url: string }>;
  triageSummary: {
    total_scanned: number;
    total_unread: number;
    summary?: string;
    patterns?: string[];
    important_emails: Array<{
      sender: string;
      subject: string;
      why_important: string;
    }>;
  } | null;
  todos: Array<{
    id: string;
    title: string;
    description?: string;
    source_email?: { sender: string; subject: string };
  }>;
  onExecuteTodo: (todoId: string) => void;
  isExecutingTodo: boolean;
  executingTodoId: string | null;
  completedTodoIds: Set<string>;
  conversationId: string | null;
  onSkipTodos: () => void;
}

type VisiblePhase = "writing_style" | "social_profiles" | "triage" | "todos";

const PHASE_ORDER: VisiblePhase[] = [
  "writing_style",
  "social_profiles",
  "triage",
  "todos",
];

const PHASE_INTRO: Record<VisiblePhase, string> = {
  writing_style: REVEAL_WRITING_STYLE_INTRO,
  social_profiles: REVEAL_SOCIAL_PROFILES_INTRO,
  triage: REVEAL_TRIAGE_INTRO,
  todos: REVEAL_TODOS_INTRO,
};

export const PHASE_BUTTON_TEXT: Partial<Record<VisiblePhase, string>> = {
  writing_style: "Looks good",
  social_profiles: "Confirm profiles",
};

export function OnboardingRevealSequence({
  revealPhase,
  writingStyle,
  profession,
  socialProfiles,
  triageSummary,
  todos,
  onExecuteTodo,
  isExecutingTodo,
  executingTodoId,
  completedTodoIds,
  conversationId,
  onSkipTodos,
}: OnboardingRevealSequenceProps) {
  const currentIndex =
    revealPhase === "complete"
      ? PHASE_ORDER.length
      : PHASE_ORDER.indexOf(revealPhase as VisiblePhase);

  const visiblePhases = PHASE_ORDER.slice(0, currentIndex + 1);

  const renderCard = (phase: VisiblePhase) => {
    switch (phase) {
      case "writing_style":
        return writingStyle ? (
          <WritingStyleRevealCard
            style_summary={writingStyle.style_summary}
            example={writingStyle.example}
            profession={profession}
          />
        ) : null;

      case "social_profiles":
        return socialProfiles.length > 0 ? (
          <SocialProfilesRevealCard profiles={socialProfiles} />
        ) : null;

      case "triage":
        return triageSummary ? <TriageRevealCard {...triageSummary} /> : null;

      case "todos":
        return todos.length > 0 ? (
          <OnboardingTodoCards
            todos={todos}
            onExecuteTodo={onExecuteTodo}
            isExecuting={isExecutingTodo}
            executingTodoId={executingTodoId}
            completedTodoIds={completedTodoIds}
          />
        ) : null;
    }
  };

  return (
    <div className="mt-3 space-y-4">
      <AnimatePresence>
        {visiblePhases.map((phase, index) => {
          return (
            <m.div
              key={phase}
              className="space-y-3"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{
                duration: 0.4,
                ease: [0.19, 1, 0.22, 1],
                delay: index * 0.05,
              }}
            >
              <ChatBubbleBot
                {...BOT_BUBBLE_DEFAULTS}
                text={PHASE_INTRO[phase]}
              />

              {renderCard(phase)}

              {phase === "todos" && conversationId && !isExecutingTodo && (
                <m.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: 1.5, duration: 0.4 }}
                >
                  <Button
                    variant="light"
                    size="sm"
                    onPress={onSkipTodos}
                    className="text-zinc-500"
                  >
                    Skip for now
                  </Button>
                </m.div>
              )}
            </m.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
