"use client";

import type { ReactNode } from "react";
import { RaisedButton } from "@/components/ui/raised-button";

/** The one cyan action the real paywall renders; checkout itself is the lab's `onCheckout`. */
const CTA_COLOR = "#00bbff";

interface CheckoutDockProps {
  label: string;
  onPress: () => void;
  /** Quiet lines under the button: the yearly option, the reassurance. */
  children?: ReactNode;
}

/** The primary action, pinned to the bottom of the frame so it never scrolls away. */
export function CheckoutDock({ label, onPress, children }: CheckoutDockProps) {
  return (
    <div className="sticky bottom-0 -mx-8 mt-auto flex flex-col items-start gap-1 bg-primary-bg/95 px-8 pt-3 pb-4 backdrop-blur-xl @max-md:-mx-5 @max-md:items-stretch @max-md:px-5">
      <RaisedButton
        className="w-full max-w-sm @max-md:max-w-none"
        color={CTA_COLOR}
        size="lg"
        onClick={onPress}
      >
        {label}
      </RaisedButton>
      <div className="flex w-full max-w-sm justify-center @max-md:max-w-none">
        {children}
      </div>
    </div>
  );
}
