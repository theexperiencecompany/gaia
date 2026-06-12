"use client";

import dynamic from "next/dynamic";

import { useVoiceSession } from "@/features/chat/components/voice-agent/VoiceSessionContext";
import { useVoiceSessionId } from "@/stores/voiceModeStore";

// next/dynamic with ssr:false keeps WebGL2 out of the SSR / RSC payload and
// gives the gradient its own client-only mount boundary. This is what makes
// the gradient render in `nx dev web` (without it, dev-mode StrictMode's
// double-mount of the heavy WebGL init effect tears down the GL context on
// first cleanup, so the second mount inherits a dead canvas).
const VoiceGradient = dynamic(
  () =>
    import("@/features/chat/components/voice-agent/VoiceGradient").then(
      (m) => m.VoiceGradient,
    ),
  { ssr: false },
);

/**
 * Renders the WebGL2 voice gradient absolutely behind the whole chat area
 * when a voice session is active. Returns null when there is no session
 * (text mode) so the gradient is fully tree-shaken from the text-mode path.
 *
 * The `key={voiceSessionId}` on the gradient forces a fresh canvas + a fresh
 * WebGL context every time `enterVoiceMode()` mints a new session id. This
 * makes Turbopack HMR and React StrictMode re-runs safe: any prior
 * torn-down GL state can never bleed into the new session.
 */
export function VoiceModeBackground() {
  const session = useVoiceSession();
  const voiceSessionId = useVoiceSessionId();
  if (!session) return null;

  // -z-10 (z-index: -10) is the only Tailwind class that ACTUALLY paints
  // the gradient behind sibling static-positioned content. `-z-0` resolves
  // to z-index:0 — a positioned descendant at z-index 0 still paints on top
  // of static block-level siblings, which would cover the messages entirely.
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
