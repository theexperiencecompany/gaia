export interface StreamToolDataEntry {
  tool_name: string;
  data: unknown;
  timestamp?: string | null;
  tool_category?: string;
}

export interface StreamToolOutput {
  tool_call_id: string;
  output: string;
}

export interface TodoProgressSnapshot {
  source?: string;
  todos?: Array<{ id: string; content: string; status: string }>;
}

type JsonObject = Record<string, unknown>;

export type ChatStreamEvent =
  | { type: "done" }
  | { type: "keepalive" }
  | { type: "main_response_complete" }
  | { type: "error"; error: string }
  | { type: "response"; chunk: string }
  | {
      type: "conversation_initialized";
      conversation_id?: string;
      conversation_description?: string | null;
      user_message_id?: string;
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
  | { type: "todo_progress"; snapshot: TodoProgressSnapshot }
  | { type: "follow_up_actions"; actions: string[] }
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
  };
};

export function parseChatStreamEvent(data: string): ChatStreamEvent[] {
  if (!data) return [];
  if (data === "[DONE]") return [{ type: "done" }];

  let payload: unknown;

  try {
    payload = JSON.parse(data);
  } catch {
    return [{ type: "response", chunk: data }];
  }

  if (!isObject(payload)) {
    return [{ type: "unknown", payload: { value: payload } }];
  }

  if (payload.keepalive === true) {
    return [{ type: "keepalive" }];
  }

  const events: ChatStreamEvent[] = [];

  if (typeof payload.error === "string" && payload.error.length > 0) {
    events.push({ type: "error", error: payload.error });
  }

  if (payload.main_response_complete === true) {
    events.push({ type: "main_response_complete" });
  }

  if (typeof payload.response === "string" && payload.response.length > 0) {
    events.push({ type: "response", chunk: payload.response });
  }

  if (isStringArray(payload.follow_up_actions)) {
    events.push({
      type: "follow_up_actions",
      actions: payload.follow_up_actions,
    });
  }

  if (
    isObject(payload.progress) &&
    typeof payload.progress.message === "string"
  ) {
    events.push({
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
    });
  }

  if (payload.tool_data !== undefined) {
    const entries = Array.isArray(payload.tool_data)
      ? payload.tool_data
      : [payload.tool_data];
    for (const entry of entries) {
      const normalized = toToolDataEntry(entry);
      if (normalized) {
        events.push({ type: "tool_data", entry: normalized });
      }
    }
  }

  if (isObject(payload.tool_output)) {
    const toolCallId = payload.tool_output.tool_call_id;
    const output = payload.tool_output.output;
    if (typeof toolCallId === "string" && typeof output === "string") {
      events.push({
        type: "tool_output",
        output: { tool_call_id: toolCallId, output },
      });
    }
  }

  if (isObject(payload.todo_progress)) {
    events.push({
      type: "todo_progress",
      snapshot: payload.todo_progress as TodoProgressSnapshot,
    });
  }

  const hasConversationInitData =
    typeof payload.conversation_id === "string" ||
    typeof payload.user_message_id === "string" ||
    typeof payload.bot_message_id === "string" ||
    typeof payload.stream_id === "string";

  if (hasConversationInitData) {
    events.push({
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
      bot_message_id:
        typeof payload.bot_message_id === "string"
          ? payload.bot_message_id
          : undefined,
      stream_id:
        typeof payload.stream_id === "string" ? payload.stream_id : undefined,
    });
  } else if (typeof payload.conversation_description === "string") {
    events.push({
      type: "conversation_description",
      description: payload.conversation_description,
    });
  }

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

  const nextEntry = {
    tool_name: "todo_progress",
    data: nextData,
    timestamp: new Date().toISOString(),
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
  if (entry.tool_name !== "tool_calls_data") return null;
  if (!isObject(entry.data)) return null;
  return typeof entry.data.message === "string" ? entry.data.message : null;
}
