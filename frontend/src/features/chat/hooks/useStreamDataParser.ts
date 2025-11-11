import {
  type ToolDataEntry,
  TOOLS_MESSAGE_KEYS,
} from "@/config/registries/toolRegistry";
import { posthog } from "@/lib/posthog";
import { MessageType } from "@/types/features/convoTypes";

export function parseStreamData(
  streamChunk: Partial<MessageType>,
  existingBotMessage?: MessageType | null,
): Partial<MessageType> {
  if (!streamChunk) return {};

  const result: Partial<MessageType> = {};

  // Dynamically copy all defined properties from streamChunk to result
  for (const [key, value] of Object.entries(streamChunk)) {
    if (value !== undefined) {
      // Handle new unified toolData array
      if (key === "tool_data") {
        const existingToolData = existingBotMessage?.tool_data || [];
        const newEntries = (
          Array.isArray(value) ? value : [value]
        ) as ToolDataEntry[];

        // Track each new tool usage in PostHog
        newEntries.forEach((entry) => {
          if (entry?.tool_name) {
            posthog.capture("tool:used", {
              tool_name: entry.tool_name,
              tool_category: entry.tool_category || "unknown",
              timestamp: entry.timestamp || new Date().toISOString(),
            });
          }
        });

        (result as Record<string, unknown>)[key] = [
          ...existingToolData,
          ...newEntries,
        ];
      }
      // Check if this is a legacy tool data key that needs accumulation
      else if (
        TOOLS_MESSAGE_KEYS.includes(key as (typeof TOOLS_MESSAGE_KEYS)[number])
      ) {
        // Get existing data for this tool key
        const existingData = existingBotMessage?.[key as keyof MessageType];

        if (existingData) {
          // Since we always store as arrays, existingData is guaranteed to be an array
          const existingArray = existingData as unknown[];
          (result as Record<string, unknown>)[key] = [...existingArray, value];
        } else {
          // No existing data, start with array containing this value
          (result as Record<string, unknown>)[key] = [value];
        }
      } else {
        // Non-tool data, just copy directly
        (result as Record<string, unknown>)[key] = value;
      }
    }
  }

  return result;
}
