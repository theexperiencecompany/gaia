"use client";

import dynamic from "next/dynamic";
import type { JSX } from "react";

// OpenUI is a browser-only surface (recharts, maplibre, …) — render the
// playground client-only to keep those modules out of the server bundle.
const OpenUIPlayground = dynamic(
  () =>
    import("@/features/chat/components/dev/OpenUIPlayground").then(
      (m) => m.OpenUIPlayground,
    ),
  {
    ssr: false,
    loading: () => (
      <div className="p-6 text-sm text-zinc-500">Loading playground…</div>
    ),
  },
);

export default function OpenUISamplesPage(): JSX.Element {
  return <OpenUIPlayground />;
}
