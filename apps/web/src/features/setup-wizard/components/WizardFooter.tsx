"use client";

import { ArrowLeft02Icon, ArrowRight02Icon } from "@icons";
import * as m from "motion/react-m";
import { GaiaButton } from "@/components/shared/GaiaButton";
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
          <GaiaButton variant="ghost" onPress={onBack}>
            <ArrowLeft02Icon className="size-4" />
            Back
          </GaiaButton>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          {onSkip && (
            <GaiaButton variant="default-soft" onPress={onSkip}>
              Skip for now
            </GaiaButton>
          )}
          <GaiaButton variant="primary" onPress={onContinue}>
            Continue
            <ArrowRight02Icon className="size-4" />
          </GaiaButton>
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
