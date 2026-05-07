/**
 * Top progress bar plus the floating Restart button. Steps are filled based
 * on `currentStep` (from `getProgress`) and clicking restart confirms via
 * a modal before invoking the caller-supplied `onRestart`.
 */

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
import { memo, useState } from "react";

interface OnboardingProgressProps {
  currentStep: number;
  totalSteps: number;
  onRestart?: () => void;
  isRestarting?: boolean;
}

function OnboardingProgressImpl({
  currentStep,
  totalSteps,
  onRestart,
  isRestarting = false,
}: OnboardingProgressProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Stable per-step keys derived from index (positions are intrinsically
  // stable here — totalSteps is a constant). Prefixed so clashes with other
  // route-level keys are impossible.
  const stepKey = (i: number) => `onboarding-progress-step-${i}`;
  return (
    <nav
      aria-label="Onboarding progress"
      className="fixed top-0 right-0 left-0 z-50 mx-auto flex max-w-lg items-center justify-center gap-2 px-4 py-4"
    >
      {Array.from({ length: totalSteps }, (_, i) => i).map((index) => {
        const isCompleted = index < currentStep;
        const isCurrent = index === currentStep;
        const scaleXValue = isCompleted || isCurrent ? 1 : 0;

        return (
          <m.div
            key={stepKey(index)}
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
              className="absolute inset-0 origin-left rounded-full bg-primary"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: scaleXValue }}
              transition={{ duration: 0.4, ease: "easeInOut" }}
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
                  This wipes everything GAIA set up for you so far. Generated
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
}

export const OnboardingProgress = memo(OnboardingProgressImpl);
