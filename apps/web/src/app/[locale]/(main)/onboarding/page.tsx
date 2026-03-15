"use client";

import {
  OnboardingInput,
  OnboardingMessages,
  OnboardingProgress,
} from "@/features/onboarding/components";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";
import { useOnboardingWebSocket } from "@/features/onboarding/hooks/useOnboardingWebSocket";

export default function Onboarding() {
  const {
    onboardingState,
    messagesEndRef,
    inputRef,
    handleProfessionSelect,
    handleProfessionInputChange,
    handleInputChange,
    handleSubmit,
    handleSkip,
    handleGmailSkip,
    handleConversationReady,
    handleRestart,
  } = useOnboarding();

  const { intelligenceConversationId, isIntelligenceComplete } =
    useOnboardingWebSocket(onboardingState.isProcessingPhase);

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-primary-bg backdrop-blur-2xl">
      <OnboardingProgress
        currentStep={onboardingState.currentQuestionIndex}
        totalSteps={5}
        onRestart={handleRestart}
      />

      <div className="relative z-10 flex-1 overflow-y-auto px-4 pt-20 pb-10">
        <div className="relative mx-auto max-w-2xl">
          <OnboardingMessages
            messages={onboardingState.messages}
            messagesEndRef={messagesEndRef}
            isProcessingPhase={onboardingState.isProcessingPhase}
            hasGmail={onboardingState.hasGmail}
            isIntelligenceComplete={isIntelligenceComplete}
            intelligenceConversationId={intelligenceConversationId}
            onProcessingComplete={handleConversationReady}
          />
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
            onSkip={handleSkip}
            onGmailSkip={handleGmailSkip}
          />
        </div>
      )}
    </div>
  );
}
