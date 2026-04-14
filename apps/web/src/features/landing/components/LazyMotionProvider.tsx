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
 */
const loadFeatures = () =>
  import("motion/react").then((res) => res.domAnimation);

export default function LazyMotionProvider({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <LazyMotion strict features={loadFeatures}>
      {children}
    </LazyMotion>
  );
}
