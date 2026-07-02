import { z } from "zod";

/**
 * Zod mirror of the chat SSE event vocabulary. The single source of truth for
 * the wire shapes lives on the backend at
 * `apps/api/app/models/stream_events.py`; this file documents the same frames
 * for the frontend and is used to validate each `data:` frame at the parse
 * boundary (see `parseChatStreamEvent`).
 *
 * Validation is advisory: on a mismatch the parser logs and falls through to
 * the existing duck-typed extraction, so runtime behavior for valid frames is
 * unchanged. Schemas therefore mirror what the parser *accepts* — permissive
 * where the parser is permissive (e.g. `tool_data` entries carry an open shape
 * so `mcp_app`, `todo_progress`, and per-tool variants all validate).
 */

// ---------------------------------------------------------------------------
// Structured payloads
// ---------------------------------------------------------------------------

const ToolDataEntrySchema = z
  .object({
    tool_name: z.string(),
    data: z.unknown(),
    timestamp: z.string().nullish(),
    tool_category: z.string().optional(),
    subagent_id: z.string().optional(),
  })
  // Per-tool variants (tool_calls_data, mcp_app, …) carry extra keys.
  .loose();

const ToolOutputPayloadSchema = z.object({
  tool_call_id: z.string(),
  output: z.string(),
  subagent_id: z.string().optional(),
});

const ReasoningPayloadSchema = z.object({
  content: z.string(),
  subagent_id: z.string().optional(),
});

const SubagentStartPayloadSchema = z.object({
  subagent_id: z.string(),
  subagent_name: z.string(),
  agent_type: z.string(),
  started_at: z.string(),
  icon_url: z.string().optional(),
  tool_category: z.string().optional(),
  parent_subagent_id: z.string().optional(),
});

const SubagentEndPayloadSchema = z.object({
  subagent_id: z.string(),
  duration_ms: z.number().optional(),
  token_count: z.number().nullish(),
});

const DesktopToolRequestPayloadSchema = z.object({
  request_id: z.string(),
  tool: z.string(),
  params: z.record(z.string(), z.unknown()).optional(),
  timeout_ms: z.number().optional(),
});

// ---------------------------------------------------------------------------
// Frames (the top-level object of a `data:` line)
// ---------------------------------------------------------------------------

const ResponseFrameSchema = z.object({ response: z.string() });
const ErrorFrameSchema = z.object({ error: z.string() });
const KeepaliveFrameSchema = z.object({ keepalive: z.literal(true) });
const MainResponseCompleteFrameSchema = z.object({
  main_response_complete: z.literal(true),
});
const FollowUpActionsFrameSchema = z.object({
  follow_up_actions: z.array(z.string()),
});
const ProgressFrameSchema = z.object({
  progress: z.union([z.string(), z.object({ message: z.string() }).loose()]),
});
const TodoProgressFrameSchema = z.object({
  todo_progress: z.record(z.string(), z.unknown()),
});
const ToolDataFrameSchema = z.object({
  tool_data: z.union([ToolDataEntrySchema, z.array(ToolDataEntrySchema)]),
});
const ToolOutputFrameSchema = z.object({
  tool_output: ToolOutputPayloadSchema,
});
const ReasoningFrameSchema = z.object({
  reasoning: ReasoningPayloadSchema,
});
const SubagentStartFrameSchema = z.object({
  subagent_start: SubagentStartPayloadSchema,
});
const SubagentEndFrameSchema = z.object({
  subagent_end: SubagentEndPayloadSchema,
});
const DesktopToolRequestFrameSchema = z.object({
  desktop_tool_request: DesktopToolRequestPayloadSchema,
});
const ConversationDescriptionFrameSchema = z.object({
  conversation_description: z.string(),
});

/**
 * Identity frame. Both the new-conversation (5 keys, `conversation_description`
 * may be null) and resumed-conversation (3 keys) variants carry the message +
 * stream ids, so those are required and the conversation-level fields optional.
 */
const ConversationInitializedFrameSchema = z.object({
  conversation_id: z.string().optional(),
  conversation_description: z.string().nullish(),
  user_message_id: z.string(),
  bot_message_id: z.string(),
  stream_id: z.string(),
});

export const ChatStreamFrameSchema = z.union([
  ResponseFrameSchema,
  ErrorFrameSchema,
  KeepaliveFrameSchema,
  MainResponseCompleteFrameSchema,
  FollowUpActionsFrameSchema,
  ProgressFrameSchema,
  TodoProgressFrameSchema,
  ToolDataFrameSchema,
  ToolOutputFrameSchema,
  ReasoningFrameSchema,
  SubagentStartFrameSchema,
  SubagentEndFrameSchema,
  DesktopToolRequestFrameSchema,
  ConversationInitializedFrameSchema,
  ConversationDescriptionFrameSchema,
]);
