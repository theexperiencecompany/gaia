"use client";

import { useEffect } from "react";
import { useHeyGaia } from "@/features/wake-word";
import { useElectron } from "@/hooks/useElectron";

/**
 * Headless wake-word listener.
 *
 * Loaded by a hidden Electron window that runs for the lifetime of the
 * desktop app. Listens for "Hey GAIA" on-device and notifies the main
 * process, which summons the assistant popup. Renders a minimal status
 * readout for debugging (the window is never shown).
 */
export default function WakeListenerPage() {
  const { isElectron, notifyWakeWord } = useElectron();
  const { state, lastDetection, error } = useHeyGaia({ enabled: isElectron });

  useEffect(() => {
    if (lastDetection) notifyWakeWord();
  }, [lastDetection, notifyWakeWord]);

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-1 bg-black font-mono text-xs text-zinc-500">
      <p>wake-listener: {state}</p>
      {error && <p className="px-4 text-red-400">{error.message}</p>}
    </div>
  );
}
