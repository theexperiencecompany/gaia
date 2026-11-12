"use client";

import { LazyArtifactRenderer } from "@/features/artifacts/LazyArtifactRenderer";
import type { PublicOpenUIArtifact } from "@/types/features/shortLinkTypes";

/** The paper copy the PDF export prints: light, no page chrome. */
export function PrintOpenUIArtifactView({
  view,
}: {
  view: PublicOpenUIArtifact;
}) {
  return (
    <main data-artifact-print className="light min-h-dvh bg-white">
      <LazyArtifactRenderer program={view.program} appearance="light" />
    </main>
  );
}
