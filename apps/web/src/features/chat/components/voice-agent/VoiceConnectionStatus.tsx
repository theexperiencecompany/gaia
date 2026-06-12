"use client";

import Image from "next/image";

import { useVoiceSession } from "@/features/chat/components/voice-agent/VoiceSessionContext";

/**
 * Voice-specific connection status chip. Renders while the LiveKit room is
 * still negotiating or the agent has not yet joined. Hidden once the agent
 * transitions to `listening | thinking | speaking`.
 *
 * Distinct from the chat `LoadingIndicator` (driven by `loadingStore`) which
 * only fires for genuine "agent is thinking" turns.
 */
export function VoiceConnectionStatus() {
  const session = useVoiceSession();
  if (!session) return null;

  const { agentState, isConnecting } = session;
  const agentReady =
    agentState === "listening" ||
    agentState === "thinking" ||
    agentState === "speaking";
  if (!isConnecting && agentReady) return null;

  return (
    <div className="flex justify-center pb-2">
      <div className="inline-flex items-center gap-2 rounded-full bg-zinc-800/80 px-3 py-1.5 text-sm text-zinc-300 shadow-md backdrop-blur">
        <Image
          alt=""
          src="/images/logos/logo.webp"
          width={16}
          height={16}
          className="animate-pulse"
        />
        Preparing voice mode…
      </div>
    </div>
  );
}
