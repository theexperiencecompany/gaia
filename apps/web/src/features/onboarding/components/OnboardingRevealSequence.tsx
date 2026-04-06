"use client";

import { Button } from "@heroui/button";
import { Spinner } from "@heroui/spinner";
import { AnimatePresence, m } from "motion/react";

import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";

import {
  REVEAL_TODOS_INTRO,
  REVEAL_WRITING_STYLE_INTRO,
} from "../constants/messages";
import type { RevealPhase } from "../hooks/useOnboardingFlow";
import { OnboardingTodoCards } from "./OnboardingTodoCards";
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
  isWaitingForNextPhase: boolean;
  waitingStatus: string | null;
  writingStyle: { style_summary: string; example?: string } | null;
  profession: string;
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
  onSkipTodos: () => void;
}

export const PHASE_BUTTON_TEXT: Partial<Record<RevealPhase, string>> = {
  writing_style: "Looks good",
};

export function OnboardingRevealSequence({
  revealPhase,
  isWaitingForNextPhase,
  waitingStatus,
  writingStyle,
  profession,
  todos,
  onExecuteTodo,
  isExecutingTodo,
  executingTodoId,
  completedTodoIds,
  onSkipTodos,
}: OnboardingRevealSequenceProps) {
  // Show writing style card for writing_style, writing_style_done, todos, complete
  const showWritingStyle =
    writingStyle &&
    (revealPhase === "writing_style" ||
      revealPhase === "writing_style_done" ||
      revealPhase === "todos" ||
      revealPhase === "complete");

  // Show todos card for todos and complete phases
  const showTodos =
    todos.length > 0 && (revealPhase === "todos" || revealPhase === "complete");

  return (
    <div className="mt-3 space-y-4">
      <AnimatePresence>
        {/* ── Writing style card ── */}
        {showWritingStyle && (
          <m.div
            key="writing_style"
            className="space-y-3"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.4,
              ease: [0.19, 1, 0.22, 1],
            }}
          >
            <ChatBubbleBot
              {...BOT_BUBBLE_DEFAULTS}
              text={REVEAL_WRITING_STYLE_INTRO}
            />
            <WritingStyleRevealCard
              style_summary={writingStyle.style_summary}
              example={writingStyle.example}
              profession={profession}
            />
          </m.div>
        )}

        {/* ── Waiting for todos indicator ── */}
        {revealPhase === "writing_style_done" && isWaitingForNextPhase && (
          <m.div
            key="waiting"
            className="space-y-3"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.4,
              ease: [0.19, 1, 0.22, 1],
              delay: 0.1,
            }}
          >
            <ChatBubbleBot
              {...BOT_BUBBLE_DEFAULTS}
              text="Looking for things I can help with..."
            >
              <div className="mt-2 ml-10.75 flex items-center gap-2">
                <Spinner size="sm" color="default" />
                <span className="text-sm text-zinc-500">
                  {waitingStatus || "Almost ready"}
                </span>
              </div>
            </ChatBubbleBot>
          </m.div>
        )}

        {/* ── Todos card ── */}
        {showTodos && (
          <m.div
            key="todos"
            className="space-y-3"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              duration: 0.4,
              ease: [0.19, 1, 0.22, 1],
              delay: 0.05,
            }}
          >
            <ChatBubbleBot {...BOT_BUBBLE_DEFAULTS} text={REVEAL_TODOS_INTRO} />

            <OnboardingTodoCards
              todos={todos}
              onExecuteTodo={onExecuteTodo}
              isExecuting={isExecutingTodo}
              executingTodoId={executingTodoId}
              completedTodoIds={completedTodoIds}
            />

            {!isExecutingTodo && (
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
        )}
      </AnimatePresence>
    </div>
  );
}
