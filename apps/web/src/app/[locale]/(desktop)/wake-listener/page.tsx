"use client";

import dynamic from "next/dynamic";
import ErrorBoundary from "@/components/shared/ErrorBoundary";

/**
 * Headless wake-word listener.
 *
 * Loaded by a hidden Electron window that runs for the lifetime of the
 * desktop app. Listens for "Hey GAIA" on-device and notifies the main
 * process, which summons the assistant popup.
 *
 * The listener body is loaded with `ssr: false` so the onnxruntime-web
 * runtime stays out of the server/Worker bundle (see WakeListenerClient).
 */
const WakeListenerClient = dynamic(
  () =>
    import("@/features/wake-word/components/WakeListenerClient").then(
      (m) => m.WakeListenerClient,
    ),
  { ssr: false },
);

export default function WakeListenerPage() {
  return (
    <ErrorBoundary>
      <WakeListenerClient />
    </ErrorBoundary>
  );
}
