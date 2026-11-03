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

/** The primary action; pinned to the bottom of a phone-width frame so it never scrolls away. */
export function CheckoutDock({ label, onPress, children }: CheckoutDockProps) {
  return (
    <div className="flex flex-col items-center gap-2 @max-md:sticky @max-md:bottom-0 @max-md:-mx-5 @max-md:mt-auto @max-md:bg-primary-bg/95 @max-md:px-5 @max-md:pt-3 @max-md:pb-5 @max-md:backdrop-blur-xl">
      <RaisedButton
        className="w-full max-w-sm"
        color={CTA_COLOR}
        size="lg"
        onClick={onPress}
      >
        {label}
      </RaisedButton>
      {children}
    </div>
  );
}
