import {
  mergeToolOutputIntoToolData,
  type StreamToolOutput,
  type TodoProgressSnapshot,
  upsertTodoProgressToolData,
} from "@shared/chat";
import type { TextStreamReader } from "livekit-client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { ToolDataEntry } from "@/config/registries/toolRegistry";

export interface VoiceStreamState {
  progress: {
    message: string;
    tool_name?: string;
    tool_category?: string;
  } | null;
  toolDataEntries: ToolDataEntry[];
  followUpActions: string[];
  todoProgress: TodoProgressSnapshot | null;
  streamError: string | null;
}

export interface VoiceStreamActions {
  clearProgress: () => void;
  clearStreamError: () => void;
}

const VOICE_STREAM_TOPICS = [
  "stream-progress",
  "stream-tool-data",
  "stream-tool-output",
  "stream-todo-progress",
  "stream-follow-up-actions",
  "stream-error",
] as const;

type VoiceTopic = (typeof VOICE_STREAM_TOPICS)[number];

const INITIAL_STATE: VoiceStreamState = {
  progress: null,
  toolDataEntries: [],
  followUpActions: [],
  todoProgress: null,
  streamError: null,
};

export function useVoiceStreamEvents(
  room: import("livekit-client").Room | null,
): VoiceStreamState & VoiceStreamActions {
  const [state, setState] = useState<VoiceStreamState>(INITIAL_STATE);
  // Ref for immediate access in async merge operations (avoids stale closure)
  const toolDataEntriesRef = useRef<ToolDataEntry[]>([]);

  const resetState = useCallback(() => {
    setState(INITIAL_STATE);
    toolDataEntriesRef.current = [];
  }, []);

  const clearProgress = useCallback(() => {
    setState((prev) =>
      prev.progress === null ? prev : { ...prev, progress: null },
    );
  }, []);

  const clearStreamError = useCallback(() => {
    setState((prev) =>
      prev.streamError === null ? prev : { ...prev, streamError: null },
    );
  }, []);

  useEffect(() => {
    if (!room) return;

    const handleTopic = (topic: VoiceTopic) => (reader: TextStreamReader) => {
      if (reader.info.topic !== topic) return;
      reader
        .readAll()
        .then((raw) => {
          let parsed: unknown;
          try {
            parsed = JSON.parse(raw);
          } catch {
            return;
          }
          if (typeof parsed !== "object" || parsed === null) return;
          const data = parsed as Record<string, unknown>;

          switch (topic) {
            case "stream-progress": {
              if (typeof data.message === "string") {
                setState((prev) => ({
                  ...prev,
                  progress: {
                    message: data.message as string,
                    tool_name:
                      typeof data.tool_name === "string"
                        ? data.tool_name
                        : undefined,
                    tool_category:
                      typeof data.tool_category === "string"
                        ? data.tool_category
                        : undefined,
                  },
                }));
              }
              break;
            }
            case "stream-tool-data": {
              const entry = data as unknown as ToolDataEntry;
              if (typeof entry.tool_name === "string") {
                // Update ref immediately for subsequent merge operations
                toolDataEntriesRef.current = [
                  ...toolDataEntriesRef.current,
                  entry,
                ];
                const updated = toolDataEntriesRef.current;
                setState((prev) => ({ ...prev, toolDataEntries: updated }));
              }
              break;
            }
            case "stream-tool-output": {
              const output = data as unknown as StreamToolOutput;
              const merged = mergeToolOutputIntoToolData(
                toolDataEntriesRef.current,
                output,
              );
              toolDataEntriesRef.current = merged;
              setState((prev) => ({ ...prev, toolDataEntries: merged }));
              break;
            }
            case "stream-todo-progress": {
              const snapshot = data as unknown as TodoProgressSnapshot;
              const updated = upsertTodoProgressToolData(
                toolDataEntriesRef.current,
                snapshot,
              );
              toolDataEntriesRef.current = updated;
              setState((prev) => ({
                ...prev,
                toolDataEntries: updated,
                todoProgress: snapshot,
              }));
              break;
            }
            case "stream-follow-up-actions": {
              if (Array.isArray(data.actions)) {
                setState((prev) => ({
                  ...prev,
                  followUpActions: data.actions as string[],
                }));
              }
              break;
            }
            case "stream-error": {
              if (typeof data.error === "string") {
                setState((prev) => ({
                  ...prev,
                  streamError: data.error as string,
                }));
              }
              break;
            }
          }
        })
        .catch(() => {
          // Ignore stream read errors
        });
    };

    const registerHandlers = () => {
      for (const topic of VOICE_STREAM_TOPICS) {
        try {
          room.unregisterTextStreamHandler(topic);
        } catch {
          // Ignore if no handler registered yet
        }
        room.registerTextStreamHandler(topic, handleTopic(topic));
      }
    };

    room.on("connected", registerHandlers);
    room.on("disconnected", resetState);

    if (room.state === "connected") {
      registerHandlers();
    }

    return () => {
      room.off("connected", registerHandlers);
      room.off("disconnected", resetState);
      for (const topic of VOICE_STREAM_TOPICS) {
        try {
          room.unregisterTextStreamHandler(topic);
        } catch {
          // Ignore
        }
      }
    };
  }, [room, resetState]);

  return { ...state, clearProgress, clearStreamError };
}
