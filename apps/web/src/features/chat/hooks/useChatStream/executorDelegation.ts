import type { ToolDataEntry } from "@/config/registries/toolRegistry";

/**
 * True when the turn handed work to a background executor — i.e. the comms
 * agent emitted a `call_executor` tool card (tagged `tool_category: "executor"`).
 *
 * Such turns don't finish their visible answer when the SSE's main response
 * completes: comms only acks synchronously ("on it"), then the executor streams
 * its tool events over the SAME SSE and delivers the real result later via a
 * `conversation.new_message` WebSocket event.
 *
 * Shared by the stream handlers (keep the spinner up through the executor
 * cold-start gap, so there's no dead frame after "delegating to executor") and
 * by stream-close (bridge into the executor-pending state).
 */
export function hasExecutorDelegation(
  toolData: ToolDataEntry[] | null | undefined,
): boolean {
  return (
    toolData?.some(
      (entry) =>
        (entry as { tool_category?: string }).tool_category === "executor",
    ) ?? false
  );
}
