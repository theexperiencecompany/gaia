import { Button } from "@heroui/button";
import { ReloadIcon } from "@icons";
import { m } from "motion/react";
import { useId } from "react";

interface OnboardingProgressProps {
  currentStep: number;
  totalSteps: number;
  onRestart?: () => void;
  onSkipSetup?: () => void;
  processingProgress?: number;
}

export const OnboardingProgress = ({
  currentStep,
  totalSteps,
  onRestart,
  onSkipSetup,
  processingProgress,
}: OnboardingProgressProps) => {
  const baseId = useId();
  const lastStepIndex = totalSteps - 1;
  return (
    <nav
      aria-label="Onboarding progress"
      className="fixed top-0 right-0 left-0 z-50 mx-auto flex max-w-lg items-center justify-center gap-2 px-4 py-4"
    >
      {Array.from({ length: totalSteps }).map((_, index) => {
        const isCompleted = index < currentStep;
        const isCurrent = index === currentStep;
        const isLastStep = index === lastStepIndex;
        const useProcessingProgress =
          isLastStep && isCurrent && processingProgress !== undefined;
        const scaleXValue = useProcessingProgress
          ? processingProgress / 100
          : isCompleted || isCurrent
            ? 1
            : 0;

        return (
          <m.div
            // biome-ignore lint/suspicious/noArrayIndexKey: Simply mapping progress data
            key={baseId + index}
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={
              isCompleted
                ? 100
                : isCurrent && scaleXValue !== undefined
                  ? Math.round(scaleXValue * 100)
                  : 0
            }
            aria-label={`Step ${index + 1} of ${totalSteps}`}
            className="relative h-0.5 flex-1 overflow-hidden rounded-full bg-zinc-800"
            initial={{ opacity: 0, scaleX: 0.8 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{
              duration: 0.3,
              delay: index * 0.1,
            }}
          >
            <m.div
              className="absolute inset-0 rounded-full bg-primary"
              initial={{ scaleX: 0 }}
              animate={{
                scaleX: scaleXValue,
              }}
              transition={{
                duration: 0.4,
                ease: "easeInOut",
              }}
              style={{
                transformOrigin: "left",
              }}
            />
          </m.div>
        );
      })}

      {onRestart && currentStep !== 0 && (
        <Button
          size="sm"
          variant="flat"
          radius="full"
          onPress={onRestart}
          className="fixed right-3 bottom-3"
          aria-label="Restart onboarding"
        >
          <ReloadIcon size={14} />
          Restart Onboarding
        </Button>
      )}

      {onSkipSetup && currentStep > 0 && (
        <button
          type="button"
          onClick={onSkipSetup}
          className="fixed right-3 bottom-12 text-xs text-zinc-600 hover:text-zinc-400 transition-colors"
          aria-label="Skip setup and go straight to GAIA"
        >
          Skip setup
        </button>
      )}
    </nav>
  );
};
