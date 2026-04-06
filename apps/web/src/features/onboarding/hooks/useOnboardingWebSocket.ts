import { useCallback, useEffect, useRef } from "react";
import type {
  OnboardingStage,
  PersonalizationData,
  StagePayloads,
} from "@/features/onboarding/types/websocket";
import { apiService } from "@/lib/api/service";

const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY_MS = 1000;
// If WebSocket hasn't delivered any events within this window, start
// a fallback REST poll so the user isn't stuck on the spinner.
const WS_FALLBACK_DELAY_MS = 5000;
const FALLBACK_POLL_INTERVAL_MS = 3000;

/**
 * Drives real-time onboarding updates over WebSocket.
 *
 * On mount a single REST check handles page-reload recovery (pipeline
 * already complete or mid-flight with persisted data).  After that,
 * WebSocket is the only delivery channel — no polling.
 *
 * An `aborted` flag guards the async mount check so React StrictMode's
 * unmount/remount cycle cannot create orphaned connections.
 */
export const useOnboardingWebSocket = (
  enabled: boolean = true,
  callbacks?: {
    onStage?: <K extends OnboardingStage>(
      stage: K,
      payload: StagePayloads[K],
    ) => void;
    onPersonalizationComplete?: (data: PersonalizationData) => void;
    onIntelligenceComplete?: (conversationId: string) => void;
    onTodoExecution?: (todoId: string, status: string, result?: string) => void;
  },
): void => {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttemptsRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const doneRef = useRef(false);
  const callbacksRef = useRef(callbacks);
  const holoFetchedRef = useRef(false);
  // Tracks which stages have been replayed to avoid duplicate events
  // from the fallback poll loop.
  const replayedRef = useRef<Set<string>>(new Set());

  // Keep callbacksRef in sync so message handlers always use the latest
  // callbacks without requiring the main effect to re-run.
  useEffect(() => {
    callbacksRef.current = callbacks;
  });

  const markDone = useCallback((conversationId: string) => {
    doneRef.current = true;
    callbacksRef.current?.onIntelligenceComplete?.(conversationId);
  }, []);

  // Fetch personalization data from REST — called when holo_ready fires
  // (payload itself is empty; the data lives in MongoDB).
  const fetchPersonalizationData = useCallback(async () => {
    if (holoFetchedRef.current) return;
    holoFetchedRef.current = true;
    try {
      const data = await apiService.get<PersonalizationData>(
        "/onboarding/personalization",
        { silent: true },
      );
      if (data?.has_personalization) {
        callbacksRef.current?.onPersonalizationComplete?.(data);
      }
    } catch {
      holoFetchedRef.current = false;
    }
  }, []);

  // Replay persisted stage data as synthetic stage events.  Idempotent —
  // safe to call from both the mount check and the fallback poll loop.
  const replayStageData = useCallback((data: PersonalizationData) => {
    const onStage = callbacksRef.current?.onStage;
    if (!onStage) return;
    const seen = replayedRef.current;

    if (data.writing_style?.style_summary && !seen.has("writing_style")) {
      seen.add("writing_style");
      onStage("writing_style_ready", {
        style_summary: data.writing_style.style_summary,
        example: data.writing_style.example ?? null,
      });
    }

    if (
      data.onboarding_todos &&
      data.onboarding_todos.length > 0 &&
      !seen.has("todos")
    ) {
      seen.add("todos");
      onStage("todos_ready", {
        todos: data.onboarding_todos,
      });
    }

    if (
      data.suggested_workflows &&
      data.suggested_workflows.length > 0 &&
      !seen.has("workflows")
    ) {
      seen.add("workflows");
      onStage("workflows_ready", {
        workflows: data.suggested_workflows,
      });
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;

    // Prevents stale async callbacks from proceeding after cleanup
    // (React StrictMode unmount/remount cycle).
    let aborted = false;
    let wsReceivedEvent = false;
    let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;

    // Lightweight fallback poll — only activates when WS fails silently.
    const startFallbackPoll = () => {
      if (pollTimer || doneRef.current || aborted) return;
      pollTimer = setInterval(async () => {
        if (doneRef.current || aborted) {
          if (pollTimer) clearInterval(pollTimer);
          pollTimer = null;
          return;
        }
        try {
          const data = await apiService.get<PersonalizationData>(
            "/onboarding/personalization",
            { silent: true },
          );
          if (aborted) return;
          replayStageData(data);
          if (data.has_personalization) {
            callbacksRef.current?.onPersonalizationComplete?.(data);
          }
          if (data.first_message_conversation_id) {
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = null;
            markDone(data.first_message_conversation_id);
          }
        } catch {
          // Keep polling
        }
      }, FALLBACK_POLL_INTERVAL_MS);
    };

    const getWsUrl = () => {
      const base =
        process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1/";
      return (
        base.replace("http://", "ws://").replace("https://", "wss://") +
        "ws/connect"
      );
    };

    const connectWs = () => {
      if (doneRef.current || aborted) return;

      try {
        const ws = new WebSocket(getWsUrl());
        wsRef.current = ws;

        ws.onopen = () => {
          reconnectAttemptsRef.current = 0;
          // Start fallback timer — if WS doesn't deliver events, poll.
          if (!wsReceivedEvent && !fallbackTimer) {
            fallbackTimer = setTimeout(() => {
              if (!wsReceivedEvent && !doneRef.current && !aborted) {
                startFallbackPoll();
              }
            }, WS_FALLBACK_DELAY_MS);
          }
        };

        ws.onmessage = (event) => {
          wsReceivedEvent = true;
          // WS is working — cancel fallback
          if (fallbackTimer) {
            clearTimeout(fallbackTimer);
            fallbackTimer = null;
          }
          if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
          }
          try {
            const message = JSON.parse(event.data) as {
              type: string;
              data: unknown;
            };

            if (message.type === "onboarding_stage") {
              const stageData = message.data as {
                stage: OnboardingStage;
                payload: StagePayloads[OnboardingStage];
              };

              callbacksRef.current?.onStage?.(
                stageData.stage,
                stageData.payload,
              );

              if (stageData.stage === "holo_ready") {
                void fetchPersonalizationData();
              }

              if (stageData.stage === "complete") {
                const p = stageData.payload as {
                  conversation_id: string | null;
                };
                if (p.conversation_id) {
                  markDone(p.conversation_id);
                }
              }
            } else if (
              message.type === "onboarding_todo_executing" ||
              message.type === "onboarding_todo_executed"
            ) {
              const { todo_id, status, result } = message.data as {
                todo_id: string;
                status: string;
                result?: string;
              };
              callbacksRef.current?.onTodoExecution?.(todo_id, status, result);
            }
          } catch (error) {
            console.error("[onboarding:ws] parse error:", error);
          }
        };

        ws.onclose = () => {
          wsRef.current = null;
          if (doneRef.current || aborted) return;

          if (reconnectAttemptsRef.current < MAX_RECONNECT_ATTEMPTS) {
            const delay =
              RECONNECT_BASE_DELAY_MS *
              2 ** Math.min(reconnectAttemptsRef.current, 5);
            reconnectAttemptsRef.current += 1;
            reconnectTimerRef.current = setTimeout(connectWs, delay);
          } else {
            // WS exhausted — fall back to polling
            startFallbackPoll();
          }
        };

        ws.onerror = () => {
          // onclose fires after onerror — reconnect handled there
        };
      } catch {
        // WebSocket constructor failed (bad URL, etc.)
      }
    };

    // ── Mount check ─────────────────────────────────────────────────
    // REST call handles page-reload recovery.  Replays any stage data
    // that's already persisted (even mid-pipeline), then connects WS
    // for remaining events if not yet complete.
    const checkOnMount = async () => {
      try {
        const data = await apiService.get<PersonalizationData>(
          "/onboarding/personalization",
          { silent: true },
        );

        if (aborted) return;

        if (data.has_personalization) {
          callbacksRef.current?.onPersonalizationComplete?.(data);
        }

        // Replay whatever data exists — even partial (mid-pipeline).
        // This lets the reveal sequence start from persisted data on reload.
        replayStageData(data);

        if (data.first_message_conversation_id) {
          markDone(data.first_message_conversation_id);
          return;
        }
      } catch {
        // Proceed with WebSocket
      }

      if (!doneRef.current && !aborted) {
        connectWs();
      }
    };

    checkOnMount();

    return () => {
      aborted = true;
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      if (fallbackTimer) {
        clearTimeout(fallbackTimer);
        fallbackTimer = null;
      }
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      holoFetchedRef.current = false;
    };
  }, [enabled, fetchPersonalizationData, replayStageData, markDone]);
};
