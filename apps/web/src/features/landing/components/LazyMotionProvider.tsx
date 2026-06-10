"use client";

import { LazyMotion } from "motion/react";
import type { ReactNode } from "react";

/**
 * Lazy-load the motion/react feature bundle (15KB domAnimation) only after the
 * page has rendered. Motion's `<m.*>` components render without JS until the
 * feature bundle arrives, at which point animations begin playing. This keeps
 * the 15KB out of the critical path.
 *
 * See https://motion.dev/docs/react-reduce-bundle-size for the pattern.
 *
 * Audit: every animated JSX node in the tree uses `<m.*>` (216 usages, 0
 * uses of `<motion.*>` as of this branch). `strict` mode is on in dev so a
 * future regression to the eager `motion` component throws loudly.
 */
const loadFeatures = () =>
  import("motion/react").then((res) => res.domAnimation);

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
