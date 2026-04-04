"use client";

import { m } from "motion/react";
import { useCallback, useEffect, useRef } from "react";
import ChatBubbleBot from "@/features/chat/components/bubbles/bot/ChatBubbleBot";
import {
  OnboardingInput,
  OnboardingMessages,
  OnboardingProgress,
} from "@/features/onboarding/components";
import { OnboardingPlatformConnect } from "@/features/onboarding/components/OnboardingPlatformConnect";
import { OnboardingRevealSequence } from "@/features/onboarding/components/OnboardingRevealSequence";
import { OnboardingWorkflowCards } from "@/features/onboarding/components/OnboardingWorkflowCards";
import { HoloCardReveal } from "@/features/onboarding/components/reveal/HoloCardReveal";
import {
  RETRY_LABEL,
  SUBMISSION_ERROR_MSG,
} from "@/features/onboarding/constants/messages";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";
import { useOnboardingChat } from "@/features/onboarding/hooks/useOnboardingChat";
import { useOnboardingFlow } from "@/features/onboarding/hooks/useOnboardingFlow";
import { useOnboardingWebSocket } from "@/features/onboarding/hooks/useOnboardingWebSocket";

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

  const {
    onboardingState,
    submissionError,
    isFocusPending,
    messagesEndRef,
    inputRef,
    handleProfessionSelect,
    handleProfessionInputChange,
    handleInputChange,
    handleSubmit,
    handleGmailSkip,
    handleEditResponse,
    handleConversationReady,
    handleRetrySubmission,
    handleRestart,
  } = useOnboarding(true);

  const flow = useOnboardingFlow(onboardingState.isProcessingPhase);

  const handleRestartAll = useCallback(() => {
    flow.reset();
    handleRestart();
  }, [flow, handleRestart]);

  const {
    chatMessages,
    chatInputValue,
    isChatSending,
    setChatInputValue,
    sendChatMessage,
  } = useOnboardingChat(flow.data.conversationId);

  useOnboardingWebSocket(onboardingState.isProcessingPhase, {
    onProgress: flow.handleProgressEvent,
    onPersonalizationComplete: flow.handlePersonalizationComplete,
    onIntelligenceComplete: (conversationId) => {
      flow.handleIntelligenceComplete(conversationId);
      void handleConversationReady(conversationId);
    },
    onTodoExecution: flow.handleTodoExecutionEvent,
  });

  // Auto-scroll on step changes and new content
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [flow.step, chatMessages.length, flow.loadingStatuses.length]);

  const handleFreeChatSubmit = useCallback(
    (e: React.FormEvent) => {
      e.preventDefault();
      const trimmed = chatInputValue.trim();
      if (!trimmed) return;
      void sendChatMessage(trimmed);
    },
    [chatInputValue, sendChatMessage],
  );

  // Determine current progress step for the progress bar
  const progressStep = (() => {
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
        processingProgress={
          flow.step.type === "loading" ? flow.progress : undefined
        }
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
            isProcessingSkipped={flow.step.type !== "loading"}
            processingProgress={
              flow.step.type === "loading" ? flow.progress : undefined
            }
            onEditMessage={handleEditResponse}
            stageMessages={flow.stageMessages}
            completedStages={flow.completedStages}
            processingContinuation={
              flow.step.type === "todos"
                ? flow.data.triageSummary
                  ? "Went through your inbox. Here's what I found:"
                  : "Set up some tasks based on your profile:"
                : undefined
            }
            processingContinuationChildren={
              flow.step.type === "todos" ? (
                <OnboardingRevealSequence
                  revealPhase={flow.revealPhase}
                  onAdvance={flow.advanceRevealPhase}
                  writingStyle={flow.data.writingStyle}
                  socialProfiles={flow.data.socialProfiles}
                  triageSummary={flow.data.triageSummary}
                  todos={flow.data.todos}
                  onExecuteTodo={flow.executeTodo}
                  isExecutingTodo={flow.isExecutingTodo}
                  executingTodoId={flow.executingTodoId}
                  completedTodoIds={flow.completedTodoIds}
                  conversationId={flow.data.conversationId}
                  onSkipTodos={flow.advanceToWorkflows}
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
                </ChatBubbleBot>
              )}

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

              {/* Chat messages */}
              {chatMessages.map((msg) => (
                <m.div
                  key={msg.id}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, ease: [0.19, 1, 0.22, 1] }}
                  className={
                    msg.role === "user"
                      ? "flex justify-end"
                      : "flex justify-start"
                  }
                >
                  <div
                    className={
                      msg.role === "user"
                        ? "max-w-[85%] rounded-2xl bg-blue-600/20 px-4 py-3 text-sm text-zinc-100 leading-relaxed"
                        : "max-w-[85%] rounded-2xl bg-zinc-800/60 px-4 py-3 text-sm text-zinc-200 leading-relaxed"
                    }
                  >
                    {msg.content || (
                      <span className="flex items-center gap-1.5 text-zinc-500">
                        <span
                          className="inline-block size-1.5 rounded-full bg-zinc-500 animate-bounce"
                          style={{ animationDelay: "0ms" }}
                        />
                        <span
                          className="inline-block size-1.5 rounded-full bg-zinc-500 animate-bounce"
                          style={{ animationDelay: "150ms" }}
                        />
                        <span
                          className="inline-block size-1.5 rounded-full bg-zinc-500 animate-bounce"
                          style={{ animationDelay: "300ms" }}
                        />
                      </span>
                    )}
                  </div>
                </m.div>
              ))}
            </m.div>
          )}

          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* ── Bottom input area ── */}
      <div className="relative z-10 mx-auto w-full max-w-lg pb-3">
        {submissionError && onboardingState.isProcessingPhase ? (
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
            freeChatValue={chatInputValue}
            onFreeChatChange={setChatInputValue}
            onFreeChatSubmit={handleFreeChatSubmit}
            isSending={isChatSending}
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
