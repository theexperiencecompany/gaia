/**
 * Top progress bar plus the floating Restart button. Steps are filled based
 * on `currentStep` (from `getProgress`) and clicking restart confirms via
 * a modal before invoking the caller-supplied `onRestart`.
 */

import { Button, Modal } from "@heroui/react";
import { RedoIcon } from "@icons";
import * as m from "motion/react-m";
import { memo, useState } from "react";
import { useIsMobile } from "@/hooks/ui/useMobile";

interface OnboardingProgressProps {
  currentStep: number;
  totalSteps: number;
  onRestart?: () => void;
  isRestarting?: boolean;
}

const stepKey = (i: number) => `onboarding-progress-step-${i}`;

function OnboardingProgressImpl({
  currentStep,
  totalSteps,
  onRestart,
  isRestarting = false,
}: OnboardingProgressProps) {
  const isMobile = useIsMobile();
  const [confirmOpen, setConfirmOpen] = useState(false);
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
          variant="tertiary"
          onPress={() => setConfirmOpen(true)}
          isPending={isRestarting}
          isDisabled={isRestarting}
          isIconOnly={isMobile}
          // A phone has no spare bottom edge (the composer lives there), so
          // the restart is a small icon in the top-right corner instead.
          className={
            isMobile ? "fixed top-3 right-3 z-20" : "fixed right-3 bottom-3"
          }
          aria-label="Restart onboarding"
        >
          {isMobile ? (
            !isRestarting && <RedoIcon size={16} />
          ) : isRestarting ? (
            "Restarting…"
          ) : (
            <>
              {!(isRestarting || isMobile) && <RedoIcon size={14} />}
              Restart Onboarding
            </>
          )}
        </Button>
      )}

      <Modal isOpen={confirmOpen} onOpenChange={setConfirmOpen}>
        <Modal.Backdrop>
          <Modal.Container placement="center" size="md">
            <Modal.Dialog>
              <Modal.CloseTrigger aria-label="Close" />
              <Modal.Header>
                <Modal.Heading>Start from scratch?</Modal.Heading>
              </Modal.Header>
              <Modal.Body>
                <p className="text-sm text-zinc-400">
                  This wipes your answers, linked apps and what I've learned
                  about you. Nothing about your subscription changes.
                </p>
              </Modal.Body>
              <Modal.Footer>
                <Button
                  variant="tertiary"
                  onPress={() => setConfirmOpen(false)}
                >
                  Cancel
                </Button>
                <Button
                  onPress={() => {
                    setConfirmOpen(false);
                    onRestart?.();
                  }}
                  variant="danger"
                >
                  Restart
                </Button>
              </Modal.Footer>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </nav>
  );
}

export const OnboardingProgress = memo(OnboardingProgressImpl);
