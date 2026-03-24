"use client";

import {
  OnboardingInput,
  OnboardingMessages,
  OnboardingProgress,
} from "@/features/onboarding/components";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";
import { useOnboardingReveal } from "@/features/onboarding/hooks/useOnboardingReveal";
import { useOnboardingWebSocket } from "@/features/onboarding/hooks/useOnboardingWebSocket";
import { useRouter } from "@/i18n/navigation";

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
          />

          {reveal.isRevealComplete && (
            <div className="mt-6 flex justify-center">
              <button
                type="button"
                onClick={() => {
                  if (reveal.intelligenceConversationId) {
                    router.push(`/c/${reveal.intelligenceConversationId}`);
                  }
                }}
                disabled={!reveal.intelligenceConversationId}
                className="bg-blue-600 hover:bg-blue-500 text-white font-medium px-6 py-3 rounded-xl transition-colors disabled:opacity-50"
              >
                Let's go →
              </button>
            </div>
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
