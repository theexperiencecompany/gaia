import type { StreamToolDataEntry } from "@shared/chat";

/**
 * True when the turn handed work to a background executor — i.e. the comms
 * agent emitted a `call_executor` tool card (tagged `tool_category: "executor"`).
 *
 * Such turns don't finish their visible answer when the SSE's main response
 * completes: comms only acks synchronously ("on it"), then the executor streams
 * its tool events over the SAME SSE and delivers the real result later via a
 * `conversation.new_message` WebSocket event.
 */
export function hasExecutorDelegation(
  toolData: StreamToolDataEntry[] | null | undefined,
): boolean {
  return toolData?.some((entry) => entry.tool_category === "executor") ?? false;
}
