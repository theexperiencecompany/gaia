import {
  DESKTOP_TOOL_DEFAULT_TIMEOUT_MS,
  type DesktopToolRequest,
} from "../desktop-tools";
import { ChatStreamFrameSchema } from "./schema";
import type { TodoProgressSnapshot } from "./types";

export type { TodoProgressSnapshot };

export interface StreamToolDataEntry {
  tool_name: string;
  data: unknown;
  timestamp?: string | null;
  tool_category?: string;
  subagent_id?: string;
}

/**
 * tool_name marking a streamed tool-call-progress entry. These render via the
 * unified tool thread (not the per-tool renderers) and carry reasoning deltas.
 */
export const TOOL_CALLS_DATA_TOOL_NAME = "tool_calls_data";

export interface StreamToolOutput {
  tool_call_id: string;
  output: string;
  subagent_id?: string;
}

type JsonObject = Record<string, unknown>;

export interface SubagentStartPayload {
  subagent_id: string;
  subagent_name: string;
  agent_type: "handoff" | "spawned";
  started_at: string;
  icon_url?: string;
  tool_category?: string;
  parent_subagent_id?: string;
}

export interface SubagentEndPayload {
  subagent_id: string;
  duration_ms: number | undefined;
  token_count: number | null;
}

export type ChatStreamEvent =
  | { type: "done" }
  | { type: "keepalive" }
  | { type: "main_response_complete" }
  | { type: "error"; error: string }
  | { type: "model_fallback"; model?: string }
  | { type: "response"; chunk: string }
  // End of one assistant message. `discarded` means that message turned out to
  // carry tool calls, so the text it streamed was a handoff preamble and the
  // real reply is the NEXT message — the wire hands over the text before the
  // tool call, so the client has already rendered it and has to take it back.
  | { type: "message_boundary"; messageId: string; discarded: boolean }
  | {
      type: "conversation_initialized";
      conversation_id?: string;
      conversation_description?: string | null;
      /** Equals the client's send id (turn_id) when the client provided one —
       *  the optimistic record already carries the final key. */
      user_message_id?: string;
      /** The user message text — replay alone can reconstruct the record if
       *  the client's local write never committed before a reload. */
      user_message_content?: string;
      bot_message_id?: string;
      stream_id?: string;
    }
  | { type: "conversation_description"; description: string }
  | {
      type: "progress";
      message: string;
      tool_name?: string;
      tool_category?: string;
    }
  | { type: "tool_data"; entry: StreamToolDataEntry }
  | { type: "tool_output"; output: StreamToolOutput }
  | { type: "reasoning"; content: string; subagent_id?: string }
  | { type: "todo_progress"; snapshot: TodoProgressSnapshot }
  | { type: "follow_up_actions"; actions: string[] }
  | { type: "subagent_start"; payload: SubagentStartPayload }
  | { type: "subagent_end"; payload: SubagentEndPayload }
  | { type: "desktop_tool_request"; request: DesktopToolRequest }
  | { type: "token_usage" }
  // A frame that was not valid JSON. Never rendered — consumers must log it
  // loudly and surface a stream error instead of showing garbage text.
  | { type: "parse_error"; raw: string }
  | { type: "unknown"; payload: JsonObject };

const isObject = (value: unknown): value is JsonObject =>
  typeof value === "object" && value !== null;

const isStringArray = (value: unknown): value is string[] =>
  Array.isArray(value) && value.every((item) => typeof item === "string");

const toToolDataEntry = (value: unknown): StreamToolDataEntry | null => {
  if (!isObject(value)) return null;
  if (typeof value.tool_name !== "string") return null;

  return {
    tool_name: value.tool_name,
    data: value.data,
    timestamp:
      typeof value.timestamp === "string" || value.timestamp === null
        ? value.timestamp
        : undefined,
    tool_category:
      typeof value.tool_category === "string" ? value.tool_category : undefined,
    subagent_id:
      typeof value.subagent_id === "string" ? value.subagent_id : undefined,
  };
};

/**
 * Advisory validation against the typed frame vocabulary (schema.ts). Never
 * gates rendering: valid frames pass silently, and an unmodeled or malformed
 * frame is surfaced in dev then handled by the same duck-typed extraction the
 * caller runs regardless — so runtime behavior for valid frames is unchanged.
 */
const warnIfFrameUnrecognized = (payload: JsonObject): void => {
  if (
    process.env.NODE_ENV !== "production" &&
    !ChatStreamFrameSchema.safeParse(payload).success
  ) {
    console.error(
      "[chat-stream] frame failed schema validation (extend schema.ts if this is a real frame):",
      payload,
    );
  }
};

const extractError = (payload: JsonObject): ChatStreamEvent[] =>
  typeof payload.error === "string" && payload.error.length > 0
    ? [{ type: "error", error: payload.error }]
    : [];

// The backend emits `{"model_fallback": {"model": "..."}}` at most once per
// stream when the primary model failed and the backup answered. Modeled as a
// first-class event so it isn't treated as turn content by the `unknown` path.
const extractModelFallback = (payload: JsonObject): ChatStreamEvent[] =>
  isObject(payload.model_fallback)
    ? [
        {
          type: "model_fallback",
          model:
            typeof payload.model_fallback.model === "string"
              ? payload.model_fallback.model
              : undefined,
        },
      ]
    : [];

const extractResponse = (payload: JsonObject): ChatStreamEvent[] => {
  const events: ChatStreamEvent[] = [];
  if (payload.main_response_complete === true) {
    events.push({ type: "main_response_complete" });
  }
  if (typeof payload.response === "string" && payload.response.length > 0) {
    events.push({ type: "response", chunk: payload.response });
  }
  return events;
};

const extractMessageBoundary = (payload: JsonObject): ChatStreamEvent[] => {
  const boundary = payload.message_boundary;
  if (!isObject(boundary) || typeof boundary.discarded !== "boolean") return [];
  return [
    {
      type: "message_boundary",
      messageId:
        typeof boundary.message_id === "string" ? boundary.message_id : "",
      discarded: boundary.discarded,
    },
  ];
};

const extractFollowUpActions = (payload: JsonObject): ChatStreamEvent[] =>
  isStringArray(payload.follow_up_actions)
    ? [{ type: "follow_up_actions", actions: payload.follow_up_actions }]
    : [];

// Backend emits progress as a plain string: {"progress": "message"}
// Guard against object form too: {"progress": {"message": "...", ...}}
const extractProgress = (payload: JsonObject): ChatStreamEvent[] => {
  if (typeof payload.progress === "string" && payload.progress.length > 0) {
    return [{ type: "progress", message: payload.progress }];
  }
  if (
    isObject(payload.progress) &&
    typeof payload.progress.message === "string"
  ) {
    return [
      {
        type: "progress",
        message: payload.progress.message,
        tool_name:
          typeof payload.progress.tool_name === "string"
            ? payload.progress.tool_name
            : undefined,
        tool_category:
          typeof payload.progress.tool_category === "string"
            ? payload.progress.tool_category
            : undefined,
      },
    ];
  }
  return [];
};

const extractToolData = (payload: JsonObject): ChatStreamEvent[] => {
  if (payload.tool_data === undefined) return [];
  const entries = Array.isArray(payload.tool_data)
    ? payload.tool_data
    : [payload.tool_data];
  const events: ChatStreamEvent[] = [];
  for (const entry of entries) {
    const normalized = toToolDataEntry(entry);
    if (normalized) {
      events.push({ type: "tool_data", entry: normalized });
    }
  }
  return events;
};

const extractToolOutput = (payload: JsonObject): ChatStreamEvent[] => {
  if (!isObject(payload.tool_output)) return [];
  const toolCallId = payload.tool_output.tool_call_id;
  const output = payload.tool_output.output;
  if (typeof toolCallId !== "string" || typeof output !== "string") return [];
  return [
    {
      type: "tool_output",
      output: {
        tool_call_id: toolCallId,
        output,
        subagent_id:
          typeof payload.tool_output.subagent_id === "string"
            ? payload.tool_output.subagent_id
            : undefined,
      },
    },
  ];
};

const extractSubagentStart = (payload: JsonObject): ChatStreamEvent[] => {
  if (!isObject(payload.subagent_start)) return [];
  const s = payload.subagent_start;
  if (
    typeof s.subagent_id !== "string" ||
    typeof s.subagent_name !== "string"
  ) {
    return [];
  }
  return [
    {
      type: "subagent_start",
      payload: {
        subagent_id: s.subagent_id,
        subagent_name: s.subagent_name,
        agent_type: (typeof s.agent_type === "string"
          ? s.agent_type
          : "handoff") as "handoff" | "spawned",
        started_at:
          typeof s.started_at === "string"
            ? s.started_at
            : new Date().toISOString(),
        icon_url: typeof s.icon_url === "string" ? s.icon_url : undefined,
        tool_category:
          typeof s.tool_category === "string" ? s.tool_category : undefined,
        parent_subagent_id:
          typeof s.parent_subagent_id === "string"
            ? s.parent_subagent_id
            : undefined,
      },
    },
  ];
};

const extractReasoning = (payload: JsonObject): ChatStreamEvent[] => {
  if (!isObject(payload.reasoning)) return [];
  const content = payload.reasoning.content;
  if (typeof content !== "string" || content.length === 0) return [];
  return [
    {
      type: "reasoning",
      content,
      subagent_id:
        typeof payload.reasoning.subagent_id === "string"
          ? payload.reasoning.subagent_id
          : undefined,
    },
  ];
};

const extractSubagentEnd = (payload: JsonObject): ChatStreamEvent[] => {
  if (!isObject(payload.subagent_end)) return [];
  const e = payload.subagent_end;
  if (typeof e.subagent_id !== "string") return [];
  return [
    {
      type: "subagent_end",
      payload: {
        subagent_id: e.subagent_id,
        duration_ms:
          typeof e.duration_ms === "number" ? e.duration_ms : undefined,
        token_count: typeof e.token_count === "number" ? e.token_count : null,
      },
    },
  ];
};

const extractDesktopToolRequest = (payload: JsonObject): ChatStreamEvent[] => {
  if (!isObject(payload.desktop_tool_request)) return [];
  const r = payload.desktop_tool_request;
  if (typeof r.request_id !== "string" || typeof r.tool !== "string") return [];
  return [
    {
      type: "desktop_tool_request",
      request: {
        request_id: r.request_id,
        tool: r.tool,
        params: isObject(r.params) ? r.params : {},
        timeout_ms:
          typeof r.timeout_ms === "number"
            ? r.timeout_ms
            : DESKTOP_TOOL_DEFAULT_TIMEOUT_MS,
      },
    },
  ];
};

const extractTodoProgress = (payload: JsonObject): ChatStreamEvent[] =>
  isObject(payload.todo_progress)
    ? [
        {
          type: "todo_progress",
          snapshot: payload.todo_progress as TodoProgressSnapshot,
        },
      ]
    : [];

const extractConversation = (payload: JsonObject): ChatStreamEvent[] => {
  const hasConversationInitData =
    typeof payload.conversation_id === "string" ||
    typeof payload.user_message_id === "string" ||
    typeof payload.bot_message_id === "string" ||
    typeof payload.stream_id === "string";

  if (hasConversationInitData) {
    return [
      {
        type: "conversation_initialized",
        conversation_id:
          typeof payload.conversation_id === "string"
            ? payload.conversation_id
            : undefined,
        conversation_description:
          typeof payload.conversation_description === "string" ||
          payload.conversation_description === null
            ? payload.conversation_description
            : undefined,
        user_message_id:
          typeof payload.user_message_id === "string"
            ? payload.user_message_id
            : undefined,
        user_message_content:
          typeof payload.user_message_content === "string"
            ? payload.user_message_content
            : undefined,
        bot_message_id:
          typeof payload.bot_message_id === "string"
            ? payload.bot_message_id
            : undefined,
        stream_id:
          typeof payload.stream_id === "string" ? payload.stream_id : undefined,
      },
    ];
  }

  if (typeof payload.conversation_description === "string") {
    return [
      {
        type: "conversation_description",
        description: payload.conversation_description,
      },
    ];
  }

  return [];
};

export function parseChatStreamEvent(data: string): ChatStreamEvent[] {
  if (!data) return [];
  if (data === "[DONE]") return [{ type: "done" }];

  let payload: unknown;

  try {
    payload = JSON.parse(data);
  } catch {
    // Every legitimate frame is JSON (or the [DONE] sentinel handled above).
    // Anything else is a malformed frame — fail loud downstream, never render.
    return [{ type: "parse_error", raw: data }];
  }

  if (!isObject(payload)) {
    return [{ type: "unknown", payload: { value: payload } }];
  }

  warnIfFrameUnrecognized(payload);

  if (payload.keepalive === true) {
    return [{ type: "keepalive" }];
  }

  // Order matters: subagent_start must precede reasoning so a payload carrying
  // both registers the group before the first reasoning delta routes into it.
  const events: ChatStreamEvent[] = [
    ...extractError(payload),
    ...extractModelFallback(payload),
    ...extractResponse(payload),
    ...extractMessageBoundary(payload),
    ...extractFollowUpActions(payload),
    ...extractProgress(payload),
    ...extractToolData(payload),
    ...extractToolOutput(payload),
    ...extractSubagentStart(payload),
    ...extractReasoning(payload),
    ...extractSubagentEnd(payload),
    ...extractDesktopToolRequest(payload),
    ...extractTodoProgress(payload),
    ...extractConversation(payload),
  ];

  return events.length > 0 ? events : [{ type: "unknown", payload }];
}

export function mergeToolOutputIntoToolData<T extends StreamToolDataEntry>(
  entries: T[],
  output: StreamToolOutput,
): T[] {
  return entries.map((entry) => {
    if (!isObject(entry.data)) {
      return entry;
    }

    const toolCallId = entry.data.tool_call_id;
    if (toolCallId !== output.tool_call_id) {
      return entry;
    }

    if (entry.tool_name === "mcp_app") {
      return {
        ...entry,
        data: { ...entry.data, tool_result: output.output },
      };
    }

    return {
      ...entry,
      data: { ...entry.data, output: output.output },
    };
  });
}

export function upsertTodoProgressToolData<T extends StreamToolDataEntry>(
  entries: T[],
  snapshot: TodoProgressSnapshot,
): T[] {
  const source = snapshot.source || "executor";

  const existingIndex = entries.findIndex(
    (entry) => entry.tool_name === "todo_progress",
  );

  const existingData =
    existingIndex >= 0 && isObject(entries[existingIndex]?.data)
      ? (entries[existingIndex].data as JsonObject)
      : {};

  const nextData: JsonObject = {
    ...existingData,
    [source]: snapshot,
  };

  // Preserve the FIRST tick's timestamp on replacement: the entry identity
  // (and any key anchored to its creation time) must stay stable while the
  // snapshot content updates, or the card remounts every streamed frame.
  const nextEntry = {
    tool_name: "todo_progress",
    data: nextData,
    timestamp:
      existingIndex >= 0
        ? (entries[existingIndex].timestamp ?? new Date().toISOString())
        : new Date().toISOString(),
  } as T;

  if (existingIndex >= 0) {
    return entries.map((entry, index) =>
      index === existingIndex ? nextEntry : entry,
    );
  }

  return [nextEntry, ...entries];
}

export function extractToolProgressMessage(
  entry: StreamToolDataEntry,
): string | null {
  if (entry.tool_name !== TOOL_CALLS_DATA_TOOL_NAME) return null;
  if (!isObject(entry.data)) return null;
  return typeof entry.data.message === "string" ? entry.data.message : null;
}
