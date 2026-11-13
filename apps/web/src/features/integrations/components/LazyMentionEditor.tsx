"use client";

import dynamic from "next/dynamic";
import { whenIdle } from "@/lib/idle";

const loadMentionEditor = () =>
  import("./MentionEditor").then((module) => module.MentionEditor);

/** Fetch the editor chunk this long after load at the latest, so a modal opened later finds it ready. */
const PREFETCH_TIMEOUT_MS = 4000;

// tiptap + prosemirror (~90 KB gzip) stay out of the route's initial JS.
if (typeof window !== "undefined") {
  whenIdle(loadMentionEditor, {
    timeoutMs: PREFETCH_TIMEOUT_MS,
    fallbackDelayMs: PREFETCH_TIMEOUT_MS,
  });
}

/** MentionEditor, loaded off the critical path; only modals render it. */
export const LazyMentionEditor = dynamic(loadMentionEditor, { ssr: false });
