"use client";

import dynamic from "next/dynamic";

// `agentation` is a devDependency; a static import would break production
// builds (`pnpm install --prod` / Cloudflare). Resolved only when
// NODE_ENV === "development", inlined at build so prod never references it.
const Agentation =
  process.env.NODE_ENV === "development"
    ? dynamic(
        () => import("agentation").then((m) => ({ default: m.Agentation })),
        { ssr: false },
      )
    : null;

const AGENTATION_ENDPOINT =
  process.env.NEXT_PUBLIC_AGENTATION_ENDPOINT ?? "http://localhost:4747";

export function AgentationProvider() {
  if (!Agentation) return null;
  // The annotation overlay is a browser-side dev tool — inside the
  // Electron shell (especially the compact assistant popup) it only
  // obstructs the UI.
  if (
    typeof navigator !== "undefined" &&
    navigator.userAgent.includes("Electron")
  ) {
    return null;
  }
  return <Agentation endpoint={AGENTATION_ENDPOINT} />;
}
