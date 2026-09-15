"use client";

import { defineComponent } from "@openuidev/react-lang";
import dynamic from "next/dynamic";
import React from "react";
import type { z } from "zod";
import { textDocumentSchema } from "../promptSpecs";

// Schema lives in Node-safe `../promptSpecs`; the actual editor (tiptap,
// BubbleMenu) lives in `DocumentEditor.tsx`, loaded client-only via
// `dynamic({ ssr: false })` to keep tiptap out of handler.mjs.

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

// TextDocumentView stays file-private: this module's public surface is
// the `textDocumentDef` registration below. Exporting the component
// alongside that def breaks Fast Refresh (react-refresh/only-export-components).

function TextDocumentView(props: z.infer<typeof textDocumentSchema>) {
  return <TextDocumentEditor {...props} />;
}

export const textDocumentDef = defineComponent({
  name: "TextDocument",
  description:
    "Editable rich text document card with optional metadata fields. Use for email drafts, document brainstorming, reports, and letters — never when sending a final email directly.",
  props: textDocumentSchema,
  component: ({ props }) => React.createElement(TextDocumentView, props),
});
