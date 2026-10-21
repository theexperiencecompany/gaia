"use client";

import { Button } from "@heroui/button";
import { ArrowLeft02Icon, ArrowRight02Icon } from "@icons";
import * as m from "motion/react-m";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";

interface WizardFooterProps {
  onBack: (() => void) | null;
  onContinue: () => void;
  /** Null on a step that cannot be skipped. */
  onSkip: (() => void) | null;
  /** Why Continue did not advance, shown only after an attempt. */
  continueReason: string | null;
}

export function WizardFooter({
  onBack,
  onContinue,
  onSkip,
  continueReason,
}: WizardFooterProps) {
  return (
    <m.div
      className="mt-6 flex flex-col items-center gap-3"
      {...MOTION_FADE_UP}
    >
      <div className="flex w-full items-center justify-between gap-2">
        {onBack ? (
          <Button
            variant="light"
            startContent={<ArrowLeft02Icon className="size-4" />}
            onPress={onBack}
          >
            Back
          </Button>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          {onSkip && (
            <Button variant="flat" onPress={onSkip}>
              Skip for now
            </Button>
          )}
          <Button
            color="primary"
            endContent={<ArrowRight02Icon className="size-4" />}
            onPress={onContinue}
          >
            Continue
          </Button>
        </div>
      </div>
      <p
        role="status"
        aria-live="polite"
        className="text-center text-xs leading-relaxed text-amber-400 empty:hidden"
      >
        {continueReason}
      </p>
    </m.div>
  );
}
