/**
 * Centered fade-up wrapper for stage-bottom CTAs (e.g. "Looks good",
 * "Understood"). Three composers used to repeat the same `m.div` with the
 * same MOTION_COMPOSER_CTA transition; this collapses them.
 */

"use client";

import * as m from "motion/react-m";
import type { ReactNode } from "react";
import { MOTION_COMPOSER_CTA } from "../constants/motion";

export function ComposerCTA({ children }: { children: ReactNode }) {
  return (
    <m.div className="flex justify-center pb-6" {...MOTION_COMPOSER_CTA}>
      {children}
    </m.div>
  );
}
