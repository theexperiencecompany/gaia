import { Button } from "@heroui/button";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { ReloadIcon } from "@icons";
import { m } from "motion/react";
import { useId, useState } from "react";

interface OnboardingProgressProps {
  currentStep: number;
  totalSteps: number;
  onRestart?: () => void;
  isRestarting?: boolean;
}

export const OnboardingProgress = ({
  currentStep,
  totalSteps,
  onRestart,
  isRestarting = false,
}: OnboardingProgressProps) => {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const baseId = useId();
  return (
    <nav
      aria-label="Onboarding progress"
      className="fixed top-0 right-0 left-0 z-50 mx-auto flex max-w-lg items-center justify-center gap-2 px-4 py-4"
    >
      {Array.from({ length: totalSteps }).map((_, index) => {
        const isCompleted = index < currentStep;
        const isCurrent = index === currentStep;
        const scaleXValue = isCompleted || isCurrent ? 1 : 0;

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
          onPress={() => setConfirmOpen(true)}
          isLoading={isRestarting}
          isDisabled={isRestarting}
          startContent={!isRestarting && <ReloadIcon size={14} />}
          className="fixed right-3 bottom-3"
          aria-label="Restart onboarding"
        >
          {isRestarting ? "Restarting…" : "Restart Onboarding"}
        </Button>
      )}

      <Modal
        isOpen={confirmOpen}
        onOpenChange={setConfirmOpen}
        size="md"
        backdrop="blur"
        placement="center"
      >
        <ModalContent>
          {(onClose) => (
            <>
              <ModalHeader>Restart onboarding?</ModalHeader>
              <ModalBody>
                <p className="text-sm text-zinc-400">
                  This wipes everything GAIA set up for you so far — generated
                  todos, suggested workflows, your writing style profile, and
                  the welcome conversation. You'll start over from question one.
                </p>
              </ModalBody>
              <ModalFooter>
                <Button variant="flat" onPress={onClose}>
                  Cancel
                </Button>
                <Button
                  color="danger"
                  onPress={() => {
                    onClose();
                    onRestart?.();
                  }}
                >
                  Restart
                </Button>
              </ModalFooter>
            </>
          )}
        </ModalContent>
      </Modal>
    </nav>
  );
};
