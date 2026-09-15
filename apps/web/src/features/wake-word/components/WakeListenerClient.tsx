"use client";

import { useEffect } from "react";
import { useElectron } from "@/hooks/useElectron";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { useHeyGaia } from "../hooks/useHeyGaia";

/**
 * Client-only body of the headless wake-word listener, loaded via
 * `next/dynamic` with `ssr: false` so the ~12 MiB onnxruntime-web WASM never
 * enters the server bundle — it runs only in the Electron desktop shell, and
 * bundling the WASM into the Cloudflare Worker would exceed its 10 MiB script limit.
 */
export function WakeListenerClient() {
  const { isElectron, notifyWakeWord } = useElectron();
  const { state, lastDetection, error, lastScore } = useHeyGaia({
    enabled: isElectron,
  });

  useEffect(() => {
    if (lastDetection) {
      trackEvent(ANALYTICS_EVENTS.WAKE_WORD_DETECTED);
      notifyWakeWord();
    }
  }, [lastDetection, notifyWakeWord]);

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-1 bg-black font-mono text-xs text-zinc-500">
      <p>wake-listener: {state}</p>
      <p data-wake-score>{lastScore?.toFixed(4) ?? "0"}</p>
      {error && <p className="px-4 text-red-400">{error.message}</p>}
    </div>
  );
}
