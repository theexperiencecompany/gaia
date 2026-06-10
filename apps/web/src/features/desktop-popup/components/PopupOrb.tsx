"use client";

import nextDynamic from "next/dynamic";
import type { PopupAgentState } from "../hooks/usePopupVoice";

const GaiaOrb = nextDynamic(() => import("@/components/ui/orb/GaiaOrb"), {
  ssr: false,
});

interface PopupOrbProps {
  state: PopupAgentState;
  className?: string;
}

/**
 * The popup's orb — GAIA's WebGL plasma sphere driven by the voice agent
 * state. No containing card: the canvas composites its own glow straight
 * onto the window's liquid glass.
 */
export default function PopupOrb({ state, className }: PopupOrbProps) {
  return <GaiaOrb state={state} className={className ?? "size-40"} />;
}
