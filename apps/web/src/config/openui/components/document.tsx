"use client";

import { defineComponent } from "@openuidev/react-lang";
import dynamic from "next/dynamic";
import React from "react";
import { z } from "zod";

// Public schema lives here so genericLibrary can re-export it without dragging
// @tiptap into the SSR bundle. The actual editor (with tiptap, BubbleMenu,
// etc.) lives in `DocumentEditor.tsx` and only loads on the client via
// `dynamic({ ssr: false })` — that keeps tiptap out of handler.mjs.
export const textDocumentSchema = z.object({
  title: z.string(),
  body: z.string(),
  fields: z
    .array(z.object({ label: z.string(), value: z.string() }))
    .optional(),
});

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

export const textDocumentDef = defineComponent({
  name: "TextDocument",
  description:
    "Editable rich text document card with optional metadata fields. Use for email drafts, document brainstorming, reports, and letters — never when sending a final email directly.",
  props: textDocumentSchema,
  component: ({ props }) => React.createElement(TextDocumentView, props),
});
