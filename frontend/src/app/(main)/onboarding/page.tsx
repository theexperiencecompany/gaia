"use client";

import {
  OnboardingChips,
  OnboardingComplete,
  OnboardingInput,
  OnboardingMessages,
} from "@/features/onboarding/components";
import { useOnboarding } from "@/features/onboarding/hooks/useOnboarding";

export default function Onboarding() {
  const {
    onboardingState,
    messagesEndRef,
    inputRef,
    handleChipSelect,
    handleProfessionSelect,
    handleProfessionInputChange,
    handleInputChange,
    handleSubmit,
    handleLetsGo,
  } = useOnboarding();

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#1a1a1a] backdrop-blur-2xl">
      {/* <OnboardingBackground /> */}

      {/* Messages Container */}
      <div className="relative z-10 flex-1 overflow-y-auto px-4 pt-20 pb-10">
        <div className="relative mx-auto max-w-2xl">
          <OnboardingMessages
            messages={onboardingState.messages}
            messagesEndRef={messagesEndRef}
            isOnboardingComplete={onboardingState.isOnboardingComplete}
          />
          <OnboardingChips
            onboardingState={onboardingState}
            onChipSelect={handleChipSelect}
          />
        </div>
      </div>

      {/* Fixed Input Container */}
      <div className="relative z-10 mx-auto w-full max-w-lg pb-3">
        {onboardingState.isOnboardingComplete ? (
          <OnboardingComplete onLetsGo={handleLetsGo} />
        ) : (
          <OnboardingInput
            onboardingState={onboardingState}
            onSubmit={handleSubmit}
            onInputChange={handleInputChange}
            onProfessionSelect={handleProfessionSelect}
            onProfessionInputChange={handleProfessionInputChange}
            inputRef={inputRef}
          />
        )}
      </div>
    </div>
  );
}
