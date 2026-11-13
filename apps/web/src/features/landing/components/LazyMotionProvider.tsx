"use client";

import { LazyMotion } from "motion/react";
import type { ReactNode } from "react";

/**
 * Lazy-load the motion/react feature bundle (15KB domAnimation) after the page
 * renders, keeping it out of the critical path — see
 * https://motion.dev/docs/react-reduce-bundle-size.
 *
 * Every animated node must use `<m.*>`, never eager `<motion.*>`; `strict`
 * mode in dev throws on a regression to the latter.
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
