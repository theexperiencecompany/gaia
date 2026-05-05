"use client";

import dynamic from "next/dynamic";

// `agentation` is a devDependency, so a static top-level import would break
// production builds (`pnpm install --prod` / Cloudflare deploy) at module
// resolution time. Resolve it only when NODE_ENV === "development" — the
// constant is inlined at build time so the production bundle never references
// the package.
const Agentation =
  process.env.NODE_ENV === "development"
    ? dynamic(
        () => import("agentation").then((m) => ({ default: m.Agentation })),
        { ssr: false },
      )
    : null;

export function AgentationProvider() {
  if (!Agentation) return null;
  return <Agentation />;
}
