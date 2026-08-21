// Loading-indicator hints carried by a `tool_data` event's payload. Shared by
// text chat (the turn session in features/chat/stream/turnSession.ts) and voice
// mode (useVoiceMessages) so both surface the same per-tool labelled loading
// line from the same data.

import { type ChatStreamEvent, TOOL_CALLS_DATA_TOOL_NAME } from "@shared/chat";
import type { ToolInfo } from "@/stores/streamStore";

export interface ToolDataLoadingHints {
  message: string;
  toolName?: string;
  toolCategory?: string;
  integrationName?: string;
  iconUrl?: string;
  showCategory: boolean;
}

// Pull the loading-indicator hints out of a tool_data event's payload
// (returns null if the payload carries no displayable message).
export function readToolDataLoadingHints(
  data: unknown,
): ToolDataLoadingHints | null {
  if (typeof data !== "object" || data === null) return null;
  const d = data as Record<string, unknown>;
  if (typeof d.message !== "string" || d.message.length === 0) return null;
  return {
    message: d.message,
    toolName: typeof d.tool_name === "string" ? d.tool_name : undefined,
    toolCategory:
      typeof d.tool_category === "string" ? d.tool_category : undefined,
    integrationName:
      typeof d.integration_name === "string" ? d.integration_name : undefined,
    iconUrl: typeof d.icon_url === "string" ? d.icon_url : undefined,
    showCategory: (d.show_category as boolean) ?? true,
  };
}

export interface LoadingLabel {
  text: string;
  toolInfo?: ToolInfo;
}

/**
 * The loading label one stream event implies, or null when it implies none.
 *
 * Every path that reads a chat stream needs this, not just the live turn: a run
 * resumed after an approval streams over `executor.stream_started` instead, and
 * when only the turn session knew how to read these frames, that run's label
 * froze on whatever was set before the pause.
 */
export function loadingLabelForEvent(
  event: ChatStreamEvent,
): LoadingLabel | null {
  if (event.type === "progress") {
    return {
      text: event.message,
      toolInfo: {
        toolName: event.tool_name,
        toolCategory: event.tool_category,
      },
    };
  }
  if (
    event.type === "tool_data" &&
    event.entry.tool_name === TOOL_CALLS_DATA_TOOL_NAME
  ) {
    const hints = readToolDataLoadingHints(event.entry.data);
    if (!hints) return null;
    const { message, ...toolInfo } = hints;
    return { text: message, toolInfo };
  }
  if (event.type === "unknown" && event.payload.status === "generating_image") {
    return { text: "Generating image..." };
  }
  return null;
}
