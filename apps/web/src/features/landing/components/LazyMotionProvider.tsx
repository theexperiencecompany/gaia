"use client";

import { LazyMotion } from "motion/react";
import type { ReactNode } from "react";

/**
 * Lazy-load the motion/react feature bundle only after the page has rendered.
 * Motion's `<m.*>` components render without JS until the feature bundle
 * arrives, at which point animations begin playing. This keeps the bundle out
 * of the critical path.
 *
 * `domMax` (~25KB) rather than `domAnimation` (~15KB): layout/layoutId morphs
 * (e.g. the FirstStepsWidget pill ↔ panel stretch) need the layout feature
 * set, which domAnimation does not include.
 *
 * See https://motion.dev/docs/react-reduce-bundle-size for the pattern.
 *
 * Audit: every animated JSX node in the tree uses `<m.*>` (216 usages, 0
 * uses of `<motion.*>` as of this branch). `strict` mode is on in dev so a
 * future regression to the eager `motion` component throws loudly.
 */
const loadFeatures = () => import("motion/react").then((res) => res.domMax);

export default function LazyMotionProvider({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <LazyMotion
      features={loadFeatures}
      strict={process.env.NODE_ENV !== "production"}
    >
      {children}
    </LazyMotion>
  );
}
