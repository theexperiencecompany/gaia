"use client";

import type { AgentState } from "@livekit/components-react";
import { createContext, useContext } from "react";

/**
 * Shared state for the active voice session. Populated by
 * `VoiceControlBarContainer` and consumed by the gradient (lifted up to
 * `ChatPage`) and the connection-status chip. Voice turns are no longer
 * surfaced here — they flow through `chatStore` like text-mode messages.
 */
export interface VoiceSessionValue {
  spectrum: Float32Array;
  agentState: AgentState;
  conversationId: string | null;
  /** True while the room is still negotiating (connecting / not yet connected). */
  isConnecting: boolean;
  /**
   * True once the muted-mic wave has settled flat — the gradient freezes its
   * draw loop so a muted session shows a still background instead of motion.
   */
  animationPaused: boolean;
  /**
   * Send a typed/clicked message (e.g. a follow-up suggestion) as a new voice
   * turn: renders the user bubble, closes the active bot turn, and publishes the
   * text to the agent over LiveKit.
   */
  sendUserTurn: (text: string) => Promise<void>;
}

const VoiceSessionContext = createContext<VoiceSessionValue | null>(null);

export const VoiceSessionProvider = VoiceSessionContext.Provider;

/**
 * Read the active voice session. Returns null when no voice session is
 * mounted (i.e. text mode) so callers can short-circuit without needing a
 * `voiceModeActive` flag.
 */
export function useVoiceSession(): VoiceSessionValue | null {
  return useContext(VoiceSessionContext);
}
