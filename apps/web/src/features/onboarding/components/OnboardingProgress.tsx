/**
 * Top progress bar plus the floating account menu. Steps are filled based
 * on `currentStep` (from `getProgress`). The menu names the signed-in account
 * and offers Log out — the way out for someone who signed in with the wrong
 * one — and Restart, which confirms via a modal before invoking `onRestart`.
 */

import { Dropdown, Header, Modal } from "@heroui/react";
import { Logout02Icon, RedoIcon, UserCircleIcon } from "@icons";
import * as m from "motion/react-m";
import { memo, useState } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { useIsMobile } from "@/hooks/ui/useMobile";

interface OnboardingProgressProps {
  currentStep: number;
  totalSteps: number;
  onRestart: () => void;
  isRestarting: boolean;
  email: string | undefined;
  onLogout: () => void;
}

const RESTART_KEY = "restart";
const LOGOUT_KEY = "logout";

const stepKey = (i: number) => `onboarding-progress-step-${i}`;

function OnboardingProgressImpl({
  currentStep,
  totalSteps,
  onRestart,
  isRestarting,
  email,
  onLogout,
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
              className="absolute inset-0 origin-left rounded-full bg-accent"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: scaleXValue }}
              transition={{ duration: 0.4, ease: "easeInOut" }}
            />
          </m.div>
        );
      })}

      <Dropdown>
        <GaiaButton
          shape="pill"
          size="sm"
          variant="default-soft"
          isPending={isRestarting}
          isDisabled={isRestarting}
          isIconOnly={isMobile}
          // A phone has no spare bottom edge (the composer lives there), so
          // the menu is a small icon in the top-right corner instead.
          className={
            isMobile ? "fixed top-3 right-3 z-20" : "fixed right-3 bottom-3"
          }
          aria-label="Account"
        >
          {!isRestarting && !isMobile && <UserCircleIcon size={14} />}
          {isMobile
            ? !isRestarting && <UserCircleIcon size={16} />
            : isRestarting
              ? "Restarting…"
              : (email ?? "Account")}
        </GaiaButton>
        <Dropdown.Popover placement={isMobile ? "bottom end" : "top end"}>
          <Dropdown.Menu aria-label="Account">
            <Dropdown.Section>
              {email && <Header>Signed in as {email}</Header>}
              <Dropdown.Item
                id={RESTART_KEY}
                textValue="Restart onboarding"
                isDisabled={currentStep === 0 || isRestarting}
                onAction={() => setConfirmOpen(true)}
              >
                <div className="flex flex-row items-center justify-start gap-2">
                  <RedoIcon size={16} />
                  Restart onboarding
                </div>
              </Dropdown.Item>
              <Dropdown.Item
                id={LOGOUT_KEY}
                textValue="Log out"
                variant="danger"
                onAction={onLogout}
              >
                <div className="flex flex-row items-center justify-start gap-2">
                  <Logout02Icon size={16} />
                  Log out
                </div>
              </Dropdown.Item>
            </Dropdown.Section>
          </Dropdown.Menu>
        </Dropdown.Popover>
      </Dropdown>

      <Modal isOpen={confirmOpen} onOpenChange={setConfirmOpen}>
        <Modal.Backdrop variant="blur">
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
                <GaiaButton
                  variant="default-soft"
                  onPress={() => setConfirmOpen(false)}
                >
                  Cancel
                </GaiaButton>
                <GaiaButton
                  onPress={() => {
                    setConfirmOpen(false);
                    onRestart?.();
                  }}
                  variant="danger"
                >
                  Restart
                </GaiaButton>
              </Modal.Footer>
            </Modal.Dialog>
          </Modal.Container>
        </Modal.Backdrop>
      </Modal>
    </nav>
  );
}

export const OnboardingProgress = memo(OnboardingProgressImpl);
