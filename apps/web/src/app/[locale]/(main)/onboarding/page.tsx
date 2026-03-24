"use client";

import { m } from "motion/react";
import { useRouter } from "next/navigation";
import {
  OnboardingInput,
  OnboardingMessages,
  OnboardingProgress,
} from "@/features/onboarding/components";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";
import { useOnboardingReveal } from "@/features/onboarding/hooks/useOnboardingReveal";
import { useOnboardingWebSocket } from "@/features/onboarding/hooks/useOnboardingWebSocket";
import { cn } from "@/lib/utils";

export default function Onboarding() {
  const router = useRouter();

  const {
    onboardingState,
    messagesEndRef,
    inputRef,
    handleProfessionSelect,
    handleProfessionInputChange,
    handleInputChange,
    handleSubmit,
    handleGmailSkip,
    handleSkipSetup,
    handleEditResponse,
    handleConversationReady,
    handleRestart,
  } = useOnboarding(true);

  const reveal = useOnboardingReveal();

  useOnboardingWebSocket(onboardingState.isProcessingPhase, {
    onProgress: reveal.handleProgressEvent,
    onPersonalizationComplete: reveal.handlePersonalizationComplete,
    onIntelligenceComplete: (conversationId) => {
      reveal.handleIntelligenceComplete(conversationId);
      void handleConversationReady(conversationId);
    },
  });

  const allMessages = [...onboardingState.messages, ...reveal.revealMessages];

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-primary-bg backdrop-blur-2xl">
      <OnboardingProgress
        currentStep={onboardingState.currentQuestionIndex}
        totalSteps={4}
        onRestart={handleRestart}
        onSkipSetup={
          !onboardingState.isProcessingPhase &&
          onboardingState.currentQuestionIndex > 0
            ? handleSkipSetup
            : undefined
        }
        processingProgress={
          onboardingState.isProcessingPhase ? reveal.progress : undefined
        }
      />

      <div className="relative z-10 flex-1 overflow-y-auto px-4 pt-20 pb-10">
        <div className="relative mx-auto max-w-2xl">
          <OnboardingMessages
            messages={allMessages}
            messagesEndRef={messagesEndRef}
            isProcessingPhase={onboardingState.isProcessingPhase}
            hasGmail={onboardingState.hasGmail}
            isIntelligenceComplete={reveal.isRevealComplete}
            intelligenceConversationId={reveal.intelligenceConversationId}
            onProcessingComplete={handleConversationReady}
            processingProgress={
              onboardingState.isProcessingPhase ? reveal.progress : undefined
            }
            onEditMessage={handleEditResponse}
          />

          {reveal.isRevealComplete && (
            <m.div
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              className="fixed bottom-8 left-1/2 -translate-x-1/2 z-10"
            >
              <button
                type="button"
                onClick={() => {
                  if (reveal.intelligenceConversationId) {
                    router.push(`/c/${reveal.intelligenceConversationId}`);
                  }
                }}
                disabled={!reveal.intelligenceConversationId}
                aria-label={
                  reveal.intelligenceConversationId
                    ? "Get started with GAIA"
                    : "Preparing your first conversation"
                }
                className={cn(
                  "rounded-xl px-6 py-3 font-medium transition-all text-sm",
                  reveal.intelligenceConversationId
                    ? "bg-blue-500 text-white hover:bg-blue-400 cursor-pointer"
                    : "bg-zinc-800 text-zinc-500 cursor-wait",
                )}
              >
                {reveal.intelligenceConversationId ? (
                  <>
                    Let&apos;s go <span aria-hidden="true">→</span>
                  </>
                ) : (
                  <span className="flex items-center gap-2">
                    <span className="inline-block size-3 rounded-full border-2 border-zinc-500 border-t-transparent animate-spin" />
                    Preparing your conversation...
                  </span>
                )}
              </button>
            </m.div>
          )}
        </div>
      </div>

      {!onboardingState.isProcessingPhase && (
        <div className="relative z-10 mx-auto w-full max-w-lg pb-3">
          <OnboardingInput
            onboardingState={onboardingState}
            onSubmit={handleSubmit}
            onInputChange={handleInputChange}
            onProfessionSelect={handleProfessionSelect}
            onProfessionInputChange={handleProfessionInputChange}
            inputRef={inputRef}
            onGmailSkip={handleGmailSkip}
          />
        </div>
      )}
    </div>
  );
}
