"use client";

import { m } from "motion/react";

export function OnboardingBackground() {
  return (
    <m.div
      className="absolute inset-0 z-0"
      style={{
        backgroundImage: `radial-gradient(100% 125% at 50% 100%, #000000 50%, #00bbffAA)`,
      }}
      animate={{
        opacity: [0.8, 1, 0.8],
      }}
      transition={{
        duration: 4,
        repeat: Infinity,
        ease: "easeInOut",
      }}
    />
  );
}
