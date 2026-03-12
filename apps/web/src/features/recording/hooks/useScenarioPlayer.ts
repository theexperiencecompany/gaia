"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useLoadingStore } from "@/stores/loadingStore";
import type { MessageType } from "@/types/features/convoTypes";
import type {
  BotMessageState,
  ImageState,
  LoadingState,
  Scenario,
  ScenarioPlayerPhase,
  ScenarioState,
  ThinkingState,
  TodoDataState,
  ToolCallsState,
  UserMessageState,
} from "../types/scenario";

export interface ScenarioLoadingState {
  isLoading: boolean;
  loadingText: string;
  loadingTextKey: number;
  toolInfo?: {
    toolCategory?: string;
    integrationName?: string;
    iconUrl?: string;
    showCategory?: boolean;
  };
}

export interface ScenarioPlayerResult {
  messages: MessageType[];
  partialMessage: MessageType | null;
  loadingState: ScenarioLoadingState;
  phase: ScenarioPlayerPhase;
  currentStateIndex: number;
  play: () => void;
  pause: () => void;
  reset: () => void;
}

function generateMessageId(stateIndex: number): string {
  return `rec-${stateIndex}-${Math.random().toString(36).slice(2, 9)}`;
}

function charInterval(
  text: string,
  speed: number,
  onChar: (partial: string) => void,
  onDone: () => void,
): () => void {
  let i = 0;
  const id = setInterval(() => {
    i++;
    onChar(text.slice(0, i));
    if (i >= text.length) {
      clearInterval(id);
      onDone();
    }
  }, speed);
  return () => clearInterval(id);
}

export function useScenarioPlayer(
  scenario: Scenario,
  options?: { autoPlay?: boolean; onComplete?: () => void },
): ScenarioPlayerResult {
  const { autoPlay = false, onComplete } = options ?? {};
  const setGlobalLoading = useLoadingStore((s) => s.setIsLoading);

  const [messages, setMessages] = useState<MessageType[]>([]);
  const [partialMessage, setPartialMessage] = useState<MessageType | null>(null);
  const [loadingState, setLoadingState] = useState<ScenarioLoadingState>({
    isLoading: false,
    loadingText: "",
    loadingTextKey: 0,
  });
  const [phase, setPhase] = useState<ScenarioPlayerPhase>("idle");
  const [currentStateIndex, setCurrentStateIndex] = useState(0);

  const stateIndexRef = useRef(0);
  const cleanupRef = useRef<(() => void) | null>(null);
  const pausedRef = useRef(false);

  const clearLoading = useCallback(() => {
    setLoadingState((prev) => ({ ...prev, isLoading: false, loadingText: "" }));
    setGlobalLoading(false);
  }, [setGlobalLoading]);

  const showLoading = useCallback(
    (text: string, toolInfo?: ScenarioLoadingState["toolInfo"]) => {
      setLoadingState((prev) => ({
        isLoading: true,
        loadingText: text,
        loadingTextKey: prev.loadingTextKey + 1,
        toolInfo,
      }));
      setGlobalLoading(true);
    },
    [setGlobalLoading],
  );

  const advanceToNext = useCallback(
    (pauseAfter: number) => {
      const nextIndex = stateIndexRef.current + 1;
      if (nextIndex >= scenario.states.length) {
        setTimeout(() => {
          if (!pausedRef.current) {
            setPhase("done");
            onComplete?.();
          }
        }, pauseAfter);
        return;
      }
      setTimeout(() => {
        if (!pausedRef.current) {
          stateIndexRef.current = nextIndex;
          setCurrentStateIndex(nextIndex);
        }
      }, pauseAfter);
    },
    [scenario.states.length, onComplete],
  );

  const processUserMessage = useCallback(
    (state: UserMessageState, index: number) => {
      const msgId = generateMessageId(index);
      const speed = state.typingSpeed ?? 50;
      const pauseAfter = state.pauseAfter ?? 300;

      setPartialMessage({
        type: "user",
        response: "",
        message_id: msgId,
        loading: false,
      });

      const cancel = charInterval(
        state.text,
        speed,
        (partial) => {
          setPartialMessage((prev) =>
            prev ? { ...prev, response: partial } : null,
          );
        },
        () => {
          const final: MessageType = {
            type: "user",
            response: state.text,
            message_id: msgId,
            loading: false,
          };
          setMessages((prev) => [...prev, final]);
          setPartialMessage(null);
          advanceToNext(pauseAfter);
        },
      );
      cleanupRef.current = cancel;
    },
    [advanceToNext],
  );

  const processBotMessage = useCallback(
    (state: BotMessageState, index: number) => {
      const msgId = generateMessageId(index);
      const speed = state.streamingSpeed ?? 15;
      const pauseAfter = state.pauseAfter ?? 300;

      showLoading("", undefined);

      const partial: MessageType = {
        type: "bot",
        response: "",
        message_id: msgId,
        loading: true,
        tool_data: undefined,
        follow_up_actions: undefined,
      };
      setPartialMessage(partial);

      const cancel = charInterval(
        state.text,
        speed,
        (text) => {
          setPartialMessage((prev) =>
            prev ? { ...prev, response: text } : null,
          );
        },
        () => {
          const final: MessageType = {
            type: "bot",
            response: state.text,
            message_id: msgId,
            loading: false,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            tool_data: (state.tool_data as any) ?? undefined,
            follow_up_actions: state.follow_up_actions ?? undefined,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            image_data: (state.image_data as any) ?? undefined,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            memory_data: (state.memory_data as any) ?? undefined,
          };
          clearLoading();
          setMessages((prev) => [...prev, final]);
          setPartialMessage(null);
          advanceToNext(pauseAfter);
        },
      );
      cleanupRef.current = cancel;
    },
    [showLoading, clearLoading, advanceToNext],
  );

  const processLoading = useCallback(
    (state: LoadingState) => {
      const duration = state.duration ?? 1500;
      const pauseAfter = state.pauseAfter ?? 300;
      showLoading(state.text, state.toolInfo);
      const id = setTimeout(() => {
        clearLoading();
        advanceToNext(pauseAfter);
      }, duration);
      cleanupRef.current = () => clearTimeout(id);
    },
    [showLoading, clearLoading, advanceToNext],
  );

  const processToolCalls = useCallback(
    (state: ToolCallsState, index: number) => {
      const pauseAfter = state.pauseAfter ?? 300;
      setMessages((prev) => {
        const lastBot = [...prev].reverse().find((m) => m.type === "bot");
        if (lastBot) {
          return prev.map((m) =>
            m.message_id === lastBot.message_id
              ? {
                  ...m,
                  // eslint-disable-next-line @typescript-eslint/no-explicit-any
                  tool_data: [...(m.tool_data ?? []), ...(state.entries as any)],
                }
              : m,
          );
        }
        const msgId = generateMessageId(index);
        return [
          ...prev,
          {
            type: "bot" as const,
            response: "",
            message_id: msgId,
            loading: false,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            tool_data: state.entries as any,
          },
        ];
      });
      const id = setTimeout(() => advanceToNext(pauseAfter), 0);
      cleanupRef.current = () => clearTimeout(id);
    },
    [advanceToNext],
  );

  const processThinking = useCallback(
    (state: ThinkingState, index: number) => {
      const duration = state.duration ?? 2000;
      const pauseAfter = state.pauseAfter ?? 300;
      const msgId = generateMessageId(index);
      const content = `<think>${state.content}</think>`;

      setMessages((prev) => [
        ...prev,
        {
          type: "bot" as const,
          response: content,
          message_id: msgId,
          loading: false,
        },
      ]);

      const id = setTimeout(() => advanceToNext(pauseAfter), duration);
      cleanupRef.current = () => clearTimeout(id);
    },
    [advanceToNext],
  );

  const processTodoData = useCallback(
    (state: TodoDataState, index: number) => {
      const pauseAfter = state.pauseAfter ?? 300;
      setMessages((prev) => {
        const lastBot = [...prev].reverse().find((m) => m.type === "bot");
        if (lastBot) {
          const entry = {
            tool_name: "todo_data" as const,
            tool_category: "todoist",
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            data: state.data as any,
            timestamp: null,
          };
          return prev.map((m) =>
            m.message_id === lastBot.message_id
              ? { ...m, tool_data: [...(m.tool_data ?? []), entry] }
              : m,
          );
        }
        const msgId = generateMessageId(index);
        return [
          ...prev,
          {
            type: "bot" as const,
            response: "",
            message_id: msgId,
            loading: false,
            tool_data: [
              {
                tool_name: "todo_data" as const,
                tool_category: "todoist",
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                data: state.data as any,
                timestamp: null,
              },
            ],
          },
        ];
      });
      const id = setTimeout(() => advanceToNext(pauseAfter), 0);
      cleanupRef.current = () => clearTimeout(id);
    },
    [advanceToNext],
  );

  const processImageState = useCallback(
    (state: ImageState, index: number) => {
      const pauseAfter = state.pauseAfter ?? 300;
      const msgId = generateMessageId(index);
      setMessages((prev) => [
        ...prev,
        {
          type: "bot" as const,
          response: "",
          message_id: msgId,
          loading: false,
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          image_data: state.image_data as any,
        },
      ]);
      const id = setTimeout(() => advanceToNext(pauseAfter), 0);
      cleanupRef.current = () => clearTimeout(id);
    },
    [advanceToNext],
  );

  const processPause = useCallback(
    (state: { duration?: number; pauseAfter?: number }) => {
      const duration = state.duration ?? 500;
      const pauseAfter = state.pauseAfter ?? 300;
      const id = setTimeout(() => advanceToNext(pauseAfter), duration);
      cleanupRef.current = () => clearTimeout(id);
    },
    [advanceToNext],
  );

  useEffect(() => {
    if (phase !== "playing") return;

    const state: ScenarioState = scenario.states[currentStateIndex];
    if (!state) {
      setPhase("done");
      return;
    }

    cleanupRef.current?.();
    cleanupRef.current = null;

    switch (state.type) {
      case "user_message":
        processUserMessage(state, currentStateIndex);
        break;
      case "bot_message":
        processBotMessage(state, currentStateIndex);
        break;
      case "loading":
        processLoading(state);
        break;
      case "tool_calls":
        processToolCalls(state, currentStateIndex);
        break;
      case "thinking":
        processThinking(state, currentStateIndex);
        break;
      case "todo_data":
        processTodoData(state, currentStateIndex);
        break;
      case "image":
        processImageState(state, currentStateIndex);
        break;
      case "pause":
        processPause(state);
        break;
    }
  }, [
    phase,
    currentStateIndex,
    scenario.states,
    processUserMessage,
    processBotMessage,
    processLoading,
    processToolCalls,
    processThinking,
    processTodoData,
    processImageState,
    processPause,
  ]);

  const play = useCallback(() => {
    pausedRef.current = false;
    setPhase("playing");
  }, []);

  const pause = useCallback(() => {
    pausedRef.current = true;
    cleanupRef.current?.();
    setPhase("idle");
  }, []);

  const reset = useCallback(() => {
    pausedRef.current = true;
    cleanupRef.current?.();
    stateIndexRef.current = 0;
    setMessages([]);
    setPartialMessage(null);
    clearLoading();
    setCurrentStateIndex(0);
    setPhase("idle");
    pausedRef.current = false;
  }, [clearLoading]);

  useEffect(() => {
    if (autoPlay) {
      const id = setTimeout(() => play(), 300);
      return () => clearTimeout(id);
    }
  }, [autoPlay, play]);

  useEffect(
    () => () => {
      cleanupRef.current?.();
    },
    [],
  );

  return {
    messages,
    partialMessage,
    loadingState,
    phase,
    currentStateIndex,
    play,
    pause,
    reset,
  };
}
