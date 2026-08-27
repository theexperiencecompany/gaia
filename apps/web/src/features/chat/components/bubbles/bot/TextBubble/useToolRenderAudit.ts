import { TOOL_CALLS_DATA_TOOL_NAME } from "@shared/chat";
import React from "react";

import type { ToolDataEntry } from "@/config/registries/toolRegistry";
import { streamLog } from "@/lib/streamLogger";
import { hasToolRenderer } from "./ToolRenderers";

/**
 * Dev-only audit of what the bubble did with each `tool_data` entry it was
 * handed. Recording delivery alone can't tell "the frontend never got the frame"
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
// (message, tool, position) so the recording reflects what happened to a frame,
// not how many times React re-ran.
const audited = new Set<string>();

const outcomeFor = (entry: ToolDataEntry): ToolRenderOutcome => {
  const name = entry.tool_name;
  if (name === TOOL_CALLS_DATA_TOOL_NAME || name === "subagent_group") {
    return "unified-thread";
  }
  if (entry.data == null) return "empty-data";
  if (name === "todo_progress") return "rendered";
  return hasToolRenderer(name) ? "rendered" : "no-renderer";
};

export const useToolRenderAudit = (
  messageId: string | undefined,
  toolData: ToolDataEntry[] | null | undefined,
): void => {
  React.useEffect(() => {
    if (!isDev || !messageId || !toolData) return;

    toolData.forEach((entry, index) => {
      const key = `${messageId}|${index}|${entry.tool_name}`;
      if (audited.has(key)) return;
      audited.add(key);

      const outcome = outcomeFor(entry);
      streamLog("render", `tool:${entry.tool_name}:${outcome}`, {
        detail: { messageId, index, outcome },
      });
    });
  }, [messageId, toolData]);
};
