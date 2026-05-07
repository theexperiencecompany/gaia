"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon, CircleArrowRight02Icon } from "@icons";
import { m } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import ChatBubbleUser from "@/features/chat/components/bubbles/user/ChatBubbleUser";
import {
  OnboardingInput,
  OnboardingMessages,
  OnboardingProgress,
} from "@/features/onboarding/components";
import { OnboardingPlatformConnect } from "@/features/onboarding/components/OnboardingPlatformConnect";
import {
  OnboardingRevealSequence,
  PHASE_BUTTON_TEXT,
} from "@/features/onboarding/components/OnboardingRevealSequence";
import { OnboardingWorkflowCards } from "@/features/onboarding/components/OnboardingWorkflowCards";
import { HoloCardReveal } from "@/features/onboarding/components/reveal/HoloCardReveal";
import { FIELD_NAMES } from "@/features/onboarding/constants";
import {
  RETRY_LABEL,
  SUBMISSION_ERROR_MSG,
} from "@/features/onboarding/constants/messages";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";
import { useOnboardingChat } from "@/features/onboarding/hooks/useOnboardingChat";
import { useOnboardingFlow } from "@/features/onboarding/hooks/useOnboardingFlow";
import { useOnboardingWebSocket } from "@/features/onboarding/hooks/useOnboardingWebSocket";
import { db as chatDb } from "@/lib/db/chatDb";
import { useChatStore } from "@/stores/chatStore";

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
  setOpenImage: () => {},
  setImageData: () => {},
  disableActions: true,
} as const;

export default function Onboarding() {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [workflowsConfirmed, setWorkflowsConfirmed] = useState(false);

  const {
    onboardingState,
    submissionError,
    isFocusPending,
    isRestarting,
    messagesEndRef,
    inputRef,
    handleProfessionSelect,
    handleProfessionInputChange,
    handleInputChange,
    handleSubmit,
    handleGmailSkip,
    handleConversationReady,
    handleRetrySubmission,
    handleRestart,
  } = useOnboarding(true);

  const flow = useOnboardingFlow(onboardingState.isProcessingPhase);

  const handleRestartAll = useCallback(async () => {
    const oldConversationId = flow.data.conversationId;

    // Local resets fire synchronously so the UI snaps back instantly.
    flow.reset();
    if (oldConversationId) {
      useChatStore.getState().removeConversation(oldConversationId);
      // Fire-and-forget — IndexedDB cleanup shouldn't block the visible
      // restart flow. A failure here is logged but doesn't surface to the
      // user; worst case is an orphan record in their browser DB.
      void chatDb
        .deleteConversationAndMessages(oldConversationId)
        .catch((error: unknown) => {
          console.error(
            "Failed to delete onboarding conversation from IndexedDB:",
            error,
          );
        });
    }

    // handleRestart resets local state synchronously too, then awaits the
    // backend reset call. The button keeps its loading state until that
    // finishes, but the user's UI is already on question 1.
    await handleRestart();
  }, [flow, handleRestart]);

  const chatMessages = useOnboardingChat(
    flow.data.conversationId,
    flow.data.executedTodoId ? flow.data.todoExecutionResult : null,
  );

  useOnboardingWebSocket(onboardingState.isProcessingPhase, {
    onStage: flow.handleStageEvent,
    onPersonalizationComplete: flow.handlePersonalizationComplete,
    onIntelligenceComplete: (conversationId) => {
      flow.handleIntelligenceComplete(conversationId);
      void handleConversationReady(conversationId);
    },
  });

  // Auto-scroll on step changes and new content
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [
    flow.step,
    chatMessages.streamMessages.length,
    flow.loadingStatuses.length,
  ]);

  const handleFreeChatSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = chatMessages.chatInputValue.trim();
      if (!trimmed) return;
      void chatMessages.sendChatMessage(trimmed);
    },
    [chatMessages],
  );

  // Determine current progress step for the progress bar.
  // While a restart is in flight, snap to 0 so the tabs animate back
  // immediately instead of waiting for the backend roundtrip to finish.
  const progressStep = isRestarting
    ? 0
    : (() => {
        switch (flow.step.type) {
          case "question":
            return onboardingState.currentQuestionIndex;
          case "loading":
            return 3;
          case "todos":
            return 4;
          case "workflows_and_connect":
            return 5;
          case "chat":
            return 6;
        }
      })();

  const showQAInput =
    flow.step.type === "question" ||
    (onboardingState.isProcessingPhase === false && !isFocusPending) ||
    isFocusPending;

  const isChatStep = flow.step.type === "chat";

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-primary-bg backdrop-blur-2xl">
      <OnboardingProgress
        currentStep={progressStep}
        totalSteps={6}
        onRestart={handleRestartAll}
        isRestarting={isRestarting}
      />

      <div
        ref={scrollRef}
        className="relative z-10 flex-1 overflow-y-auto px-4 pt-20 pb-10"
      >
        <div className="relative mx-auto max-w-2xl">
          {/* ── Q&A Messages ── */}
          <OnboardingMessages
            messages={onboardingState.messages}
            messagesEndRef={messagesEndRef}
            isProcessingPhase={onboardingState.isProcessingPhase}
            hasGmail={onboardingState.hasGmail}
            isIntelligenceComplete={flow.step.type === "chat"}
            intelligenceConversationId={flow.data.conversationId}
            onProcessingComplete={handleConversationReady}
            // Keep the processing checklist visible across the loading,
            // todos, and workflows phases so the user sees every step tick
            // off. It only unmounts once we transition into the chat step.
            isProcessingSkipped={flow.step.type === "chat"}
            inboxScanCount={flow.inboxScanCount}
            completedStages={flow.completedStages}
            processingStatusMessage={flow.data.waitingStatus}
            processingContinuationChildren={
              flow.step.type === "todos" ? (
                <OnboardingRevealSequence
                  revealPhase={flow.revealPhase}
                  isWaitingForNextPhase={flow.isWaitingForNextPhase}
                  waitingStatus={flow.data.waitingStatus}
                  writingStyle={flow.data.writingStyle}
                  profession={
                    onboardingState.userResponses[FIELD_NAMES.PROFESSION] ?? ""
                  }
                  todos={flow.data.todos}
                  onExecuteTodo={flow.executeTodo}
                  isExecutingTodo={flow.isExecutingTodo}
                  executingTodoId={flow.executingTodoId}
                  completedTodoIds={flow.completedTodoIds}
                  onSkipTodos={flow.advanceRevealPhase}
                />
              ) : undefined
            }
          />

          {/* ── Workflows + Platform Connect step ── */}
          {flow.step.type === "workflows_and_connect" && (
            <m.div
              className="mt-4 space-y-4"
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
            >
              {flow.data.workflows.length > 0 && (
                <ChatBubbleBot
                  {...BOT_BUBBLE_DEFAULTS}
                  text="Here's what I set up to run on a recurring basis:"
                >
                  <div className="mt-3">
                    <OnboardingWorkflowCards workflows={flow.data.workflows} />
                  </div>
                  {!workflowsConfirmed && (
                    <p className="mt-2 ml-10.75 text-xs text-zinc-500">
                      These run automatically. Customize them anytime in
                      Workflows.
                    </p>
                  )}
                </ChatBubbleBot>
              )}

              {(workflowsConfirmed || flow.data.workflows.length === 0) && (
                <m.div
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    duration: 0.4,
                    ease: [0.19, 1, 0.22, 1],
                  }}
                >
                  <ChatBubbleBot
                    {...BOT_BUBBLE_DEFAULTS}
                    text="Get notifications and talk to me on the go:"
                  >
                    <div className="mt-3">
                      <OnboardingPlatformConnect
                        onConnect={flow.connectPlatform}
                        onSkip={flow.skipPlatformConnect}
                        connectedPlatform={flow.data.connectedPlatform}
                      />
                    </div>
                  </ChatBubbleBot>
                </m.div>
              )}
            </m.div>
          )}

          {/* ── Chat step ── */}
          {isChatStep && (
            <m.div
              className="mt-4 space-y-4"
              initial={{ opacity: 0, y: 15 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
            >
              {/* Holo card if available */}
              {flow.data.holoCardData && (
                <div className="my-4">
                  <HoloCardReveal
                    personalizationData={flow.data.holoCardData}
                  />
                </div>
              )}

              {/* Streaming chat messages */}
              {chatMessages.streamMessages.map((msg) => (
                <m.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, ease: [0.19, 1, 0.22, 1] }}
                >
                  {msg.role === "user" ? (
                    <ChatBubbleUser
                      {...BOT_BUBBLE_DEFAULTS}
                      text={msg.content}
                      message_id={msg.id}
                      date={msg.createdAt.toISOString()}
                      fileData={msg.fileData}
                    />
                  ) : (
                    <ChatBubbleBot
                      {...BOT_BUBBLE_DEFAULTS}
                      text={msg.content}
                      message_id={msg.id}
                      loading={msg.status === "sending"}
                      tool_data={msg.tool_data ?? undefined}
                      todo_progress={msg.todo_progress ?? undefined}
                      memory_data={msg.memory_data ?? undefined}
                      image_data={msg.image_data ?? undefined}
                      date={msg.createdAt.toISOString()}
                    />
                  )}
                </m.div>
              ))}

              {/* Loading indicator while waiting for first assistant chunk */}
              {chatMessages.isChatSending &&
                !chatMessages.streamMessages.some(
                  (m) => m.role === "assistant" && m.content,
                ) && (
                  <m.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    className="flex items-center gap-2 pl-1"
                  >
                    <div className="min-w-10 shrink-0" />
                    <div className="flex gap-1.5">
                      {[0, 150, 300].map((delay) => (
                        <span
                          key={delay}
                          className="inline-block size-1.5 animate-bounce rounded-full bg-zinc-500"
                          style={{ animationDelay: `${delay}ms` }}
                        />
                      ))}
                    </div>
                  </m.div>
                )}

              {/* Post-todo-execution CTA */}
              {chatMessages.isTodoExecutionDone && (
                <m.div
                  className="flex justify-center pt-4"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
                >
                  <Button
                    color="primary"
                    radius="full"
                    size="md"
                    endContent={<ArrowRight02Icon className="size-4" />}
                    as="a"
                    href="/c"
                  >
                    Continue to GAIA
                  </Button>
                </m.div>
              )}
            </m.div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* ── Bottom input area ── */}
      <div className="relative z-10 mx-auto w-full max-w-lg pb-3">
        {flow.step.type === "workflows_and_connect" &&
        !workflowsConfirmed &&
        flow.data.workflows.length > 0 ? (
          <m.div
            className="flex justify-center"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.3,
              duration: 0.35,
              ease: [0.19, 1, 0.22, 1],
            }}
          >
            <Button
              color="primary"
              size="md"
              endContent={<CircleArrowRight02Icon className="size-4" />}
              onPress={() => setWorkflowsConfirmed(true)}
            >
              Understood
            </Button>
          </m.div>
        ) : flow.step.type === "todos" &&
          PHASE_BUTTON_TEXT[
            flow.revealPhase as keyof typeof PHASE_BUTTON_TEXT
          ] ? (
          <m.div
            className="flex justify-center"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{
              delay: 0.3,
              duration: 0.35,
              ease: [0.19, 1, 0.22, 1],
            }}
          >
            <Button
              color="primary"
              radius="full"
              size="md"
              endContent={<ArrowRight02Icon className="size-4" />}
              onPress={flow.advanceRevealPhase}
            >
              {
                PHASE_BUTTON_TEXT[
                  flow.revealPhase as keyof typeof PHASE_BUTTON_TEXT
                ]
              }
            </Button>
          </m.div>
        ) : submissionError && onboardingState.isProcessingPhase ? (
          <m.div
            className="flex flex-col items-center gap-2 px-4"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.4, ease: [0.19, 1, 0.22, 1] }}
          >
            <p className="text-sm text-zinc-400">{SUBMISSION_ERROR_MSG}</p>
            <button
              type="button"
              onClick={handleRetrySubmission}
              className="cursor-pointer rounded-lg bg-zinc-700 px-4 py-2 text-sm font-medium text-zinc-200 transition-colors hover:bg-zinc-600"
            >
              {RETRY_LABEL}
            </button>
          </m.div>
        ) : isChatStep ? (
          <OnboardingInput
            onboardingState={onboardingState}
            onSubmit={handleFreeChatSubmit}
            onInputChange={handleInputChange}
            onProfessionSelect={handleProfessionSelect}
            onProfessionInputChange={handleProfessionInputChange}
            inputRef={inputRef}
            isFreeChatMode
            freeChatValue={chatMessages.chatInputValue}
            onFreeChatChange={chatMessages.setChatInputValue}
            onFreeChatSubmit={handleFreeChatSubmit}
            isSending={chatMessages.isChatSending}
          />
        ) : showQAInput && flow.step.type === "question" ? (
          <OnboardingInput
            onboardingState={onboardingState}
            onSubmit={handleSubmit}
            onInputChange={handleInputChange}
            onProfessionSelect={handleProfessionSelect}
            onProfessionInputChange={handleProfessionInputChange}
            inputRef={inputRef}
            onGmailSkip={handleGmailSkip}
            isFocusPending={isFocusPending}
          />
        ) : null}
      </div>
    </div>
  );
}
