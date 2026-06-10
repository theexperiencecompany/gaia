"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLoadingStore } from "@/stores/loadingStore";
import { WAKE_ACK_AUDIO_SRC } from "../constants";

/**
 * Mirrors the voice-mode `AgentState` from the LiveKit voice agent
 * (PR #733) so the popup UI is already keyed to the same vocabulary.
 */
export type PopupAgentState = "idle" | "listening" | "thinking" | "speaking";

export interface PopupVoiceSession {
  agentState: PopupAgentState;
  /**
   * Wake the session and start listening.
   *
   * @param playAck - Play the acknowledgment sound ("mhm") — only voice
   *   summons ("Hey GAIA") should, not the keyboard shortcut.
   */
  activate: (playAck: boolean) => void;
  /** Put the session back to sleep. */
  deactivate: () => void;
}

/**
 * Voice-session seam for the assistant popup.
 *
 * Until voice mode lands, "voice" is simulated: activation plays the
 * pre-defined acknowledgment audio and the agent state is derived from
 * the text chat-stream lifecycle (loading → thinking, response
 * streaming → speaking). When the LiveKit plumbing merges, only this
 * hook's internals change — the popup UI consumes the same interface.
 */
export function usePopupVoice(): PopupVoiceSession {
  const [active, setActive] = useState(false);
  const isLoading = useLoadingStore((state) => state.isLoading);
  const isMainResponseStreaming = useLoadingStore(
    (state) => state.isMainResponseStreaming,
  );
  const ackAudioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const audio = new Audio(WAKE_ACK_AUDIO_SRC);
    audio.preload = "auto";
    ackAudioRef.current = audio;
    return () => {
      audio.pause();
      ackAudioRef.current = null;
    };
  }, []);

  const activate = useCallback((playAck: boolean) => {
    setActive(true);
    if (!playAck) return;
    const audio = ackAudioRef.current;
    if (audio) {
      audio.currentTime = 0;
      audio.play().catch((error) => {
        console.error("[desktop-popup] Failed to play wake ack:", error);
      });
    }
  }, []);

  const deactivate = useCallback(() => {
    setActive(false);
  }, []);

  let agentState: PopupAgentState = "idle";
  if (active) {
    if (isMainResponseStreaming) agentState = "speaking";
    else if (isLoading) agentState = "thinking";
    else agentState = "listening";
  }

  return { agentState, activate, deactivate };
}
