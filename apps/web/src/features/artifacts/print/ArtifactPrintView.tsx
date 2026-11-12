"use client";

import { useState } from "react";
import { ArtifactRenderer } from "../openui/ArtifactRenderer";

declare global {
  interface Window {
    /** Set by the PDF export before the page loads (app/services/openui_artifacts/export.py). */
    __GAIA_ARTIFACT_PROGRAM__?: string;
  }
}

/** The paper copy the PDF export prints: light, no page chrome, the program handed in. */
export function ArtifactPrintView() {
  const [program] = useState(() => window.__GAIA_ARTIFACT_PROGRAM__ ?? "");
  return (
    <main data-artifact-print className="light min-h-dvh bg-white">
      <ArtifactRenderer program={program} appearance="light" />
    </main>
  );
}
