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
  const { state, lastDetection } = useHeyGaia({ enabled: isElectron });

  useEffect(() => {
    if (lastDetection) notifyWakeWord();
  }, [lastDetection, notifyWakeWord]);

  return (
    <div className="flex h-screen items-center justify-center bg-black font-mono text-xs text-zinc-500">
      wake-listener: {state}
    </div>
  );
}
