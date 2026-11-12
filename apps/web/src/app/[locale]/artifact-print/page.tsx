"use client";

import dynamic from "next/dynamic";

// Client-only: the program arrives on window from the PDF export's own browser.
const ArtifactPrintView = dynamic(
  () =>
    import("@/features/artifacts/print/ArtifactPrintView").then(
      (m) => m.ArtifactPrintView,
    ),
  { ssr: false },
);

export default function ArtifactPrintPage() {
  return <ArtifactPrintView />;
}
