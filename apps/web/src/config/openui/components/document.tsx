"use client";

import dynamic from "next/dynamic";
import type { z } from "zod";
import type { textDocumentSchema } from "../promptSpecs";

// The schema lives in the Node-safe `../promptSpecs` single source. The actual
// editor (with tiptap, BubbleMenu, etc.) lives in `DocumentEditor.tsx` and only
// loads on the client via `dynamic({ ssr: false })` — that keeps tiptap out of
// handler.mjs.

const TextDocumentEditor = dynamic(
  () => import("./DocumentEditor").then((m) => m.TextDocumentView),
  {
    ssr: false,
    loading: () => (
      <div className="rounded-2xl bg-zinc-800 p-4 text-zinc-200">
        <div className="rounded-2xl bg-zinc-900 p-3">
          <div className="h-32 animate-pulse rounded bg-zinc-800" />
        </div>
      </div>
    ),
  },
);

export function TextDocumentView(props: z.infer<typeof textDocumentSchema>) {
  return <TextDocumentEditor {...props} />;
}
