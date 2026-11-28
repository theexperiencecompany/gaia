import type {
  ToolCallReasoningStep,
  ToolCallsDataEntryData,
} from "@gaia/shared/api/generated";
import type { ApprovalEnd, SubagentGroupData } from "@gaia/shared/chat";

export type ActivityStatus = "running" | "done" | "error";

/** A tool call or thinking step in a turn's activity feed; streamed partials merge by id, so any field may be missing yet. */
export type ActivityToolCall = Partial<ToolCallsDataEntryData> &
  Partial<Pick<ToolCallReasoningStep, "reasoning">> & {
    status?: ActivityStatus;
  };

/**
 * SubagentGroupData plus task/result lifted off the originating handoff/spawn
 * tool call (the backend may also supply these fields directly).
 */
export interface EnrichedSubagentGroup extends SubagentGroupData {
  handoff_input?: string;
  handoff_output?: string;
}

/** One chronological entry of the unified tool chain. */
export type TimelineItem =
  | { kind: "tool"; call: ActivityToolCall }
  | { kind: "subagent"; group: EnrichedSubagentGroup }
  | { kind: "thinking"; content: string };

/** HIL approval outcomes keyed by the gated tool call. */
export interface ApprovalLookup {
  /** tool_call_ids currently blocked on a pending approval. */
  pendingToolCallIds: Set<string>;
  /** Settled decisions keyed by tool_call_id — rendered as outcome chips. */
  statusByToolCallId: Map<string, ApprovalEnd>;
}
