import { Button } from "@heroui/button";
import { motion } from "framer-motion";

import { RotateCcw } from "@/icons";

interface OnboardingProgressProps {
  currentStep: number;
  totalSteps: number;
  onRestart?: () => void;
}

export const OnboardingProgress = ({
  currentStep,
  totalSteps,
  onRestart,
}: OnboardingProgressProps) => {
  return (
    <div className="fixed top-0 right-0 left-0 z-50 mx-auto flex max-w-lg items-center justify-center gap-2 px-4 py-4">
      {Array.from({ length: totalSteps }).map((_, index) => {
        const isCompleted = index < currentStep;
        const isCurrent = index === currentStep;

        return (
          <motion.div
            key={index}
            className="relative h-0.5 flex-1 overflow-hidden rounded-full bg-zinc-800"
            initial={{ opacity: 0, scaleX: 0.8 }}
            animate={{ opacity: 1, scaleX: 1 }}
            transition={{
              duration: 0.3,
              delay: index * 0.1,
            }}
          >
            <motion.div
              className="absolute inset-0 rounded-full bg-primary"
              initial={{ scaleX: 0 }}
              animate={{
                scaleX: isCompleted || isCurrent ? 1 : 0,
              }}
              transition={{
                duration: 0.4,
                ease: "easeInOut",
              }}
              style={{
                transformOrigin: "left",
              }}
            />
          </motion.div>
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
          <RotateCcw size={14} />
          Restart Onboarding
        </Button>
      )}
    </div>
  );
};
