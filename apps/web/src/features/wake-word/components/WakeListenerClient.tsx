"use client";

import { useEffect } from "react";
import { useElectron } from "@/hooks/useElectron";
import { useHeyGaia } from "../hooks/useHeyGaia";

/**
 * Client-only body of the headless wake-word listener.
 *
 * Pulled out of the route and loaded via `next/dynamic` with `ssr: false`
 * so the onnxruntime-web runtime (a ~12 MiB WASM module) never enters the
 * server bundle. The wake-word pipeline runs exclusively in the Electron
 * desktop shell, so server-rendering it is pure dead weight — and bundling
 * the WASM into the Cloudflare Worker pushes it past the 10 MiB script
 * limit. Keeping it client-only confines onnxruntime-web to the browser
 * chunk where it belongs.
 */
export function WakeListenerClient() {
  const { isElectron, notifyWakeWord } = useElectron();
  const { state, lastDetection, error, lastScore } = useHeyGaia({
    enabled: isElectron,
  });

  useEffect(() => {
    if (lastDetection) notifyWakeWord();
  }, [lastDetection, notifyWakeWord]);

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-1 bg-black font-mono text-xs text-zinc-500">
      <p>wake-listener: {state}</p>
      <p data-wake-score>{lastScore?.toFixed(4) ?? "0"}</p>
      {error && <p className="px-4 text-red-400">{error.message}</p>}
    </div>
  );
}
