// Loading-indicator hints carried by a `tool_data` event's payload. Shared by
// text chat (the turn session in features/chat/stream/turnSession.ts) and voice
// mode (useVoiceMessages) so both surface the same per-tool labelled loading
// line from the same data.

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
