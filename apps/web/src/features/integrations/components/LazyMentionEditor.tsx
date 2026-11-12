"use client";

import dynamic from "next/dynamic";

const loadMentionEditor = () =>
  import("./MentionEditor").then((module) => module.MentionEditor);

// tiptap + prosemirror (~90 KB gzip) stay out of the route's initial JS; the
// chunk is fetched at idle so a modal that opens later finds it ready.
if (typeof window !== "undefined") {
  requestIdleCallback(() => void loadMentionEditor());
}

/** MentionEditor, loaded off the critical path; only modals render it. */
export const LazyMentionEditor = dynamic(loadMentionEditor, { ssr: false });
