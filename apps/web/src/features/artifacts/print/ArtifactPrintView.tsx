"use client";

import { useSyncExternalStore } from "react";
import { ArtifactRenderer } from "../openui/ArtifactRenderer";

declare global {
  interface Window {
    /** Set by the PDF export before the page loads (app/services/openui_artifacts/export.py). */
    __GAIA_ARTIFACT_PROGRAM__?: string;
  }
}

/** The paper copy the PDF export prints: light, no page chrome, the program handed in. */
const subscribeNever = () => () => undefined;
const programFromWindow = () => window.__GAIA_ARTIFACT_PROGRAM__ ?? "";
const noProgramOnServer = () => "";

export function ArtifactPrintView() {
  const program = useSyncExternalStore(
    subscribeNever,
    programFromWindow,
    noProgramOnServer,
  );
  return (
    <main data-artifact-print className="light min-h-dvh bg-white">
      <ArtifactRenderer program={program} appearance="light" />
    </main>
  );
}
