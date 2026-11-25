import type { TimelineCard, ToolTimeline } from "@shared/api/generated";
import React from "react";

import { streamLog } from "@/lib/streamLogger";
import { hasToolRenderer } from "./ToolRenderers";

/**
 * Dev-only audit of what the bubble did with each row and card of the timeline
 * it was handed. Recording delivery alone can't tell "the frontend never got the frame"
 * apart from "it got it and rendered nothing" — this closes that gap by logging
 * the outcome of every entry into the same stream recording as the SSE frames.
 */

type ToolRenderOutcome =
  /** Handed to a registered TOOL_RENDERERS card. */
  | "rendered"
  /** Folded into UnifiedToolThread instead of a card (by design). */
  | "unified-thread"
  /** No TOOL_RENDERERS entry — renderTool returns null and nothing appears. */
  | "no-renderer"
  /** Entry arrived with an empty payload — TextBubble bails before rendering. */
  | "empty-data";

const isDev = process.env.NODE_ENV !== "production";

// The bubble re-renders on every streamed frame. Outcomes are logged once per
// (message, row or card key) so the recording reflects what happened to a frame,
// not how many times React re-ran.
const audited = new Set<string>();

const outcomeFor = (card: TimelineCard["card"]): ToolRenderOutcome => {
  if (card.data == null) return "empty-data";
  if (card.tool_name === "todo_progress") return "rendered";
  return hasToolRenderer(card.tool_name) ? "rendered" : "no-renderer";
};

export const useToolRenderAudit = (
  messageId: string | undefined,
  timeline: ToolTimeline | undefined,
): void => {
  React.useEffect(() => {
    if (!isDev || !messageId || !timeline) return;

    const record = (key: string, name: string, outcome: ToolRenderOutcome) => {
      const seen = `${messageId}|${key}`;
      if (audited.has(seen)) return;
      audited.add(seen);
      streamLog("render", `tool:${name}:${outcome}`, {
        detail: { messageId, key, outcome },
      });
    };
    for (const step of timeline.steps)
      record(step.key, step.kind, "unified-thread");
    for (const { key, card } of timeline.cards)
      record(key, card.tool_name, outcomeFor(card));
  }, [messageId, timeline]);
};
