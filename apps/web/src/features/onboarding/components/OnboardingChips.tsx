import { Chip } from "@heroui/chip";
import { m } from "motion/react";

import { questions } from "../constants";
import type { OnboardingState } from "../types";

interface OnboardingChipsProps {
  onboardingState: OnboardingState;
  onChipSelect: (questionId: string, chipValue: string) => void;
}

export const OnboardingChips = ({
  onboardingState,
  onChipSelect,
}: OnboardingChipsProps) => {
  if (
    onboardingState.currentQuestionIndex >= questions.length ||
    !questions[onboardingState.currentQuestionIndex].chipOptions ||
    onboardingState.isProcessing ||
    onboardingState.hasAnsweredCurrentQuestion
  ) {
    return null;
  }

  const currentQuestion = questions[onboardingState.currentQuestionIndex];

  return (
    <m.div
      key={`chips-${currentQuestion.id}`}
      className="mb-4"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.3,
        ease: "easeOut",
        delay: onboardingState.messages.length * 0.05 + 0.1,
      }}
    >
      <div className="flex flex-wrap gap-2">
        {currentQuestion.chipOptions!.map((option, index) => (
          <m.div
            key={option.value}
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{
              duration: 0.25,
              ease: "easeOut",
              delay:
                onboardingState.messages.length * 0.05 + 0.15 + index * 0.05,
            }}
          >
            <Chip
              className="cursor-pointer"
              color="primary"
              size="sm"
              variant="flat"
              onClick={() => onChipSelect(currentQuestion.id, option.value)}
            >
              {option.label}
            </Chip>
          </m.div>
        ))}
      </div>
    </m.div>
  );
};
