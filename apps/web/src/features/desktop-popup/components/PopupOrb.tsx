"use client";

import * as m from "motion/react-m";
import type { PopupAgentState } from "../hooks/usePopupVoice";

interface PulseProfile {
  scale: number[];
  opacity: number[];
  duration: number;
}

/** Breathing/pulsing motion per agent state. */
const PULSE: Record<PopupAgentState, PulseProfile> = {
  idle: { scale: [1, 1.04, 1], opacity: [0.45, 0.6, 0.45], duration: 4 },
  listening: { scale: [1, 1.1, 1], opacity: [0.8, 1, 0.8], duration: 2 },
  thinking: { scale: [1, 0.93, 1], opacity: [0.65, 0.95, 0.65], duration: 1.1 },
  speaking: { scale: [1, 1.16, 1], opacity: [0.85, 1, 0.85], duration: 0.65 },
};

/**
 * The glowing GAIA orb — placeholder for the voice-mode WebGL orb
 * from PR #733; swap the internals, keep the `state` prop.
 */
export default function PopupOrb({ state }: { state: PopupAgentState }) {
  const pulse = PULSE[state];

  return (
    <div className="relative flex size-20 items-center justify-center">
      {/* outer halo */}
      <m.div
        className="absolute -inset-4 rounded-full bg-primary/35 blur-2xl"
        animate={{ scale: pulse.scale, opacity: pulse.opacity }}
        transition={{
          duration: pulse.duration,
          repeat: Number.POSITIVE_INFINITY,
          ease: "easeInOut",
        }}
      />
      {/* sonar wave while listening */}
      {state === "listening" && (
        <m.div
          className="absolute inset-1 rounded-full bg-primary/25"
          initial={{ scale: 1, opacity: 0.5 }}
          animate={{ scale: 1.7, opacity: 0 }}
          transition={{
            duration: 1.6,
            repeat: Number.POSITIVE_INFINITY,
            ease: "easeOut",
          }}
        />
      )}
      {/* core sphere */}
      <m.div
        className="relative size-14 rounded-full shadow-lg"
        style={{
          background:
            "radial-gradient(circle at 30% 28%, #b8efff 0%, #4ed4ff 38%, #00bbff 62%, #0078c2 100%)",
        }}
        animate={{ scale: pulse.scale }}
        transition={{
          duration: pulse.duration,
          repeat: Number.POSITIVE_INFINITY,
          ease: "easeInOut",
        }}
      />
    </div>
  );
}
