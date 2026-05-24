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
import { RedoIcon } from "@icons";
import * as m from "motion/react-m";
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
  const stepKey = (i: number) => `onboarding-progress-step-${i}`;
  return (
    <nav
      aria-label="Onboarding progress"
      className="fixed top-0 right-0 left-0 z-50 mx-auto flex max-w-3xl items-center justify-center gap-2 px-4 py-4"
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
          startContent={!isRestarting && <RedoIcon size={14} />}
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
                  This wipes everything GAIA set up for you so far and starts
                  you over from question one. The following will be cleared:
                </p>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-zinc-400">
                  <li>
                    Connected integrations (Gmail, Calendar, Slack, and any
                    others) will be{" "}
                    <span className="text-zinc-200">disconnected</span> — you'll
                    need to reconnect them.
                  </li>
                  <li>Suggested workflows and their schedules</li>
                  <li>Onboarding todos</li>
                  <li>Your writing style and triage profile</li>
                  <li>The welcome conversation and its agent memory</li>
                </ul>
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
