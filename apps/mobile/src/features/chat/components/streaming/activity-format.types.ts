import type { ApprovalStatus, SubagentGroupData } from "@gaia/shared/chat";

/** A single tool call inside a turn's chronological activity feed. */
export interface ActivityToolCall {
  tool_call_id?: string;
  tool_name?: string;
  tool_category?: string;
  message?: string;
  inputs?: Record<string, unknown>;
  output?: string;
  integration_name?: string;
  icon_url?: string;
  show_category?: boolean;
  /** Model thinking for this step — renders as a Thinking row, not a tool. */
  reasoning?: string;
  status?: "running" | "done" | "error";
}

export type ActivityStatus = "running" | "done" | "error";

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
  statusByToolCallId: Map<string, ApprovalStatus>;
}
