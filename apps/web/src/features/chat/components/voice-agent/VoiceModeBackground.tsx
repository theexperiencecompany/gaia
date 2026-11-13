"use client";

import dynamic from "next/dynamic";

import { useVoiceSession } from "@/features/chat/components/voice-agent/VoiceSessionContext";
import { useVoiceSessionId } from "@/stores/voiceModeStore";

// next/dynamic ssr:false keeps WebGL2 out of SSR/RSC and gives its own
// client-only mount boundary — without it, dev StrictMode's double-mount
// tears down the GL context on first cleanup, leaving a dead canvas.
const VoiceGradient = dynamic(
  () =>
    import("@/features/chat/components/voice-agent/VoiceGradient").then(
      (m) => m.VoiceGradient,
    ),
  { ssr: false },
);

/**
 * Renders the WebGL2 voice gradient behind the chat area during a voice
 * session; null (fully tree-shaken) in text mode.
 *
 * `key={voiceSessionId}` forces a fresh canvas + WebGL context per new
 * session id, so Turbopack HMR / StrictMode re-runs can't bleed torn-down GL state into the new session.
 */
export function VoiceModeBackground() {
  const session = useVoiceSession();
  const voiceSessionId = useVoiceSessionId();
  if (!session) return null;

  // -z-10 is the only Tailwind class that actually paints the gradient
  // behind static siblings — `-z-0` resolves to z-index:0, where a
  // positioned descendant still paints over static block-level content.
  return (
    <div className="pointer-events-none absolute inset-0 -z-10 overflow-hidden">
      <VoiceGradient
        key={voiceSessionId ?? "no-session"}
        mode="gaia"
        spectrum={session.spectrum}
        paused={session.animationPaused}
      />
    </div>
  );
}
