"use client";

import { domAnimation, LazyMotion } from "motion/react";
import type { ReactNode } from "react";

export default function LazyMotionProvider({
  children,
}: {
  children: ReactNode;
}) {
  return <LazyMotion features={domAnimation}>{children}</LazyMotion>;
}
