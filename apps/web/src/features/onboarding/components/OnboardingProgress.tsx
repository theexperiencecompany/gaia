/**
 * Top progress bar plus the floating account menu. Steps are filled based
 * on `currentStep` (from `getProgress`). The menu names the signed-in account
 * and offers Log out — the way out for someone who signed in with the wrong
 * one — and Restart, which confirms via a modal before invoking `onRestart`.
 */

import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownSection,
  DropdownTrigger,
} from "@heroui/dropdown";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Logout02Icon, RedoIcon, UserCircleIcon } from "@icons";
import * as m from "motion/react-m";
import { memo, useState } from "react";
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
              className="absolute inset-0 origin-left rounded-full bg-primary"
              initial={{ scaleX: 0 }}
              animate={{ scaleX: scaleXValue }}
              transition={{ duration: 0.4, ease: "easeInOut" }}
            />
          </m.div>
        );
      })}

      <Dropdown placement={isMobile ? "bottom-end" : "top-end"}>
        <DropdownTrigger>
          <Button
            size="sm"
            variant="flat"
            radius="full"
            isLoading={isRestarting}
            isIconOnly={isMobile}
            startContent={
              !isRestarting && !isMobile && <UserCircleIcon size={14} />
            }
            // A phone has no spare bottom edge (the composer lives there), so
            // the menu is a small icon in the top-right corner instead.
            className={
              isMobile ? "fixed top-3 right-3 z-20" : "fixed right-3 bottom-3"
            }
            aria-label="Account"
          >
            {isMobile
              ? !isRestarting && <UserCircleIcon size={16} />
              : isRestarting
                ? "Restarting…"
                : (email ?? "Account")}
          </Button>
        </DropdownTrigger>
        <DropdownMenu
          aria-label="Account"
          disabledKeys={currentStep === 0 || isRestarting ? [RESTART_KEY] : []}
          onAction={(key) => {
            if (key === RESTART_KEY) setConfirmOpen(true);
            if (key === LOGOUT_KEY) onLogout();
          }}
        >
          <DropdownSection title={email ? `Signed in as ${email}` : undefined}>
            <DropdownItem
              key={RESTART_KEY}
              startContent={<RedoIcon size={16} />}
            >
              Restart onboarding
            </DropdownItem>
            <DropdownItem
              key={LOGOUT_KEY}
              color="danger"
              className="text-danger"
              startContent={<Logout02Icon size={16} />}
            >
              Log out
            </DropdownItem>
          </DropdownSection>
        </DropdownMenu>
      </Dropdown>

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
              <ModalHeader>Start from scratch?</ModalHeader>
              <ModalBody>
                <p className="text-sm text-zinc-400">
                  This wipes your answers, linked apps and what I've learned
                  about you. Nothing about your subscription changes.
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
                    onRestart();
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
