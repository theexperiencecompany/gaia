"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiService } from "@/lib/api/service";

import type {
  OnboardingStage,
  PersonalizationData,
  StagePayloads,
} from "../types/websocket";

// ── Step State Machine ───────────────────────────────────────────────────────

export type OnboardingStep =
  | { type: "question"; index: number }
  | { type: "loading" }
  | { type: "todos" }
  | { type: "workflows_and_connect" }
  | { type: "chat" };

export type RevealPhase =
  | "writing_style" // card visible, "Looks good" button
  | "writing_style_done" // user confirmed, waiting for todos data
  | "todos" // todos card visible
  | "complete"; // auto-transitions to workflows step

export interface OnboardingFlowData {
  todos: Array<{
    id: string;
    title: string;
    description?: string;
    source_email?: { sender: string; subject: string };
  }>;
  workflows: Array<{
    id?: string;
    title: string;
    description?: string;
    categories?: string[];
  }>;
  writingStyle: { style_summary: string; example?: string } | null;
  waitingStatus: string | null;
  holoCardData: PersonalizationData | null;
  conversationId: string | null;
  connectedPlatform: string | null;
  executedTodoId: string | null;
  todoExecutionResult: string | null;
}

interface LoadingStatus {
  message: string;
  timestamp: number;
}

export interface UseOnboardingFlowReturn {
  step: OnboardingStep;
  data: OnboardingFlowData;
  loadingStatuses: LoadingStatus[];
  inboxScanCount: number;
  completedStages: Set<OnboardingStage>;
  isExecutingTodo: boolean;
  executingTodoId: string | null;
  completedTodoIds: Set<string>;
  revealPhase: RevealPhase;
  isWaitingForNextPhase: boolean;
  advanceRevealPhase: () => void;
  advanceToWorkflows: () => void;
  advanceToChat: () => void;
  executeTodo: (todoId: string) => void;
  connectPlatform: (platform: string) => void;
  skipPlatformConnect: () => void;
  handleStageEvent: <K extends OnboardingStage>(
    stage: K,
    payload: StagePayloads[K],
  ) => void;
  handlePersonalizationComplete: (data: PersonalizationData) => void;
  handleIntelligenceComplete: (conversationId: string) => void;
  reset: () => void;
}

const INITIAL_DATA: OnboardingFlowData = {
  todos: [],
  workflows: [],
  writingStyle: null,
  waitingStatus: null,
  holoCardData: null,
  conversationId: null,
  connectedPlatform: null,
  executedTodoId: null,
  todoExecutionResult: null,
};

export function useOnboardingFlow(
  isProcessingPhase: boolean,
): UseOnboardingFlowReturn {
  const [step, setStep] = useState<OnboardingStep>({
    type: "question",
    index: 0,
  });
  const [data, setData] = useState<OnboardingFlowData>(INITIAL_DATA);
  const [loadingStatuses, setLoadingStatuses] = useState<LoadingStatus[]>([]);
  const [inboxScanCount, setInboxScanCount] = useState(0);
  const [completedStages, setCompletedStages] = useState<Set<OnboardingStage>>(
    new Set(),
  );
  const [revealPhase, setRevealPhase] = useState<RevealPhase>("writing_style");
  const [isWaitingForNextPhase, setIsWaitingForNextPhase] = useState(false);
  const [isExecutingTodo, setIsExecutingTodo] = useState(false);
  const [executingTodoId, setExecutingTodoId] = useState<string | null>(null);
  const [completedTodoIds, setCompletedTodoIds] = useState<Set<string>>(
    new Set(),
  );

  const intelligenceCompleteRef = useRef(false);
  // Refs that mirror state so stable callbacks can read current values.
  const dataRef = useRef(data);
  dataRef.current = data;
  const revealPhaseRef = useRef(revealPhase);
  revealPhaseRef.current = revealPhase;
  const isWaitingRef = useRef(isWaitingForNextPhase);
  isWaitingRef.current = isWaitingForNextPhase;

  // Transition to loading step when processing phase starts
  useEffect(() => {
    if (isProcessingPhase && step.type === "question") {
      setStep({ type: "loading" });
    }
  }, [isProcessingPhase, step.type]);

  // ── Auto-advance from "complete" reveal to workflows step ───────────────
  useEffect(() => {
    if (revealPhase !== "complete") return;
    setStep((prev) =>
      prev.type === "todos" || prev.type === "loading"
        ? { type: "workflows_and_connect" }
        : prev,
    );
  }, [revealPhase]);

  const handleStageEvent = useCallback(
    <K extends OnboardingStage>(stage: K, payload: StagePayloads[K]) => {
      if (stage === "inbox_scanning") {
        const p = payload as StagePayloads["inbox_scanning"];
        setInboxScanCount(p.current);
        setLoadingStatuses((prev) => [
          ...prev,
          {
            message: `${p.current} emails fetched`,
            timestamp: Date.now(),
          },
        ]);
        return;
      }

      setCompletedStages((prev) => new Set([...prev, stage]));

      // Enter reveal as soon as first card has data.
      const enterRevealSequence = () => {
        setStep((prev) => (prev.type === "loading" ? { type: "todos" } : prev));
      };

      switch (stage) {
        case "writing_style_ready": {
          const p = payload as StagePayloads["writing_style_ready"];
          if (p.style_summary) {
            setData((prev) => ({
              ...prev,
              writingStyle: {
                style_summary: p.style_summary as string,
                example: p.example ?? undefined,
              },
            }));
            enterRevealSequence();
          }
          break;
        }
        case "todos_ready": {
          const p = payload as StagePayloads["todos_ready"];
          if (p.todos.length > 0) {
            setData((prev) => ({ ...prev, todos: p.todos }));
            enterRevealSequence();
          }

          // Resolve reveal phase exactly once based on current state.
          const currentPhase = revealPhaseRef.current;
          const hasWritingStyle = dataRef.current.writingStyle !== null;

          if (currentPhase === "writing_style_done") {
            // User already clicked "Looks good" — advance.
            setRevealPhase(p.todos.length > 0 ? "todos" : "complete");
            setIsWaitingForNextPhase(false);
          } else if (!hasWritingStyle && p.todos.length > 0) {
            // Writing style never arrived — start reveal at todos.
            setRevealPhase("todos");
          }
          break;
        }
        case "workflows_ready": {
          const p = payload as StagePayloads["workflows_ready"];
          setData((prev) => ({ ...prev, workflows: p.workflows }));
          break;
        }
        case "triage_analyzing": {
          const p = payload as StagePayloads["triage_analyzing"];
          setData((prev) => ({ ...prev, waitingStatus: p.status }));
          break;
        }
        case "triage_analyzed": {
          const p = payload as StagePayloads["triage_analyzed"];
          setData((prev) => ({ ...prev, waitingStatus: p.status }));
          break;
        }
        case "todos_creating": {
          const p = payload as StagePayloads["todos_creating"];
          setData((prev) => ({ ...prev, waitingStatus: p.status }));
          break;
        }
        case "holo_ready":
        case "social_profiles_ready":
        case "triage_ready":
        case "complete":
          break;
      }
    },
    [],
  );

  const handlePersonalizationComplete = useCallback(
    (personalizationData: PersonalizationData) => {
      setData((prev) => ({ ...prev, holoCardData: personalizationData }));
    },
    [],
  );

  const handleIntelligenceComplete = useCallback((conversationId: string) => {
    intelligenceCompleteRef.current = true;
    setData((prev) => ({ ...prev, conversationId }));

    // If still on loading (nothing triggered reveal), transition now.
    setStep((s) => {
      if (s.type !== "loading") return s;
      // Check if there's any reveal data at all via the ref-accessible state
      // updater pattern — read `prev` from the setData above.
      return { type: "workflows_and_connect" };
    });

    // If user is in the waiting state (clicked "Looks good" but todos
    // haven't arrived), the pipeline finishing means todos won't come.
    // Auto-advance to complete.
    if (
      revealPhaseRef.current === "writing_style_done" &&
      isWaitingRef.current
    ) {
      setRevealPhase("complete");
      setIsWaitingForNextPhase(false);
    }
  }, []);

  const advanceRevealPhase = useCallback(() => {
    setRevealPhase((prev) => {
      if (prev === "writing_style") {
        // Check if todos are ready
        if (dataRef.current.todos.length > 0) {
          return "todos";
        }
        if (intelligenceCompleteRef.current) {
          // Pipeline done, no todos — skip to complete
          return "complete";
        }
        // Todos haven't arrived yet — enter waiting state
        setIsWaitingForNextPhase(true);
        return "writing_style_done";
      }
      if (prev === "todos" || prev === "writing_style_done") {
        return "complete";
      }
      return "complete";
    });
  }, []);

  const advanceToWorkflows = useCallback(() => {
    setStep({ type: "workflows_and_connect" });
  }, []);

  const advanceToChat = useCallback(() => {
    setStep({ type: "chat" });
    void apiService.post("/onboarding/phase", { phase: "getting_started" });
  }, []);

  // Execute a todo by transitioning to chat mode and sending the task as
  // a message.  The normal chat streaming infra handles the live execution UX.
  const executeTodo = useCallback(
    (todoId: string) => {
      if (isExecutingTodo) return;
      const todo = dataRef.current.todos.find((t) => t.id === todoId);
      if (!todo) return;

      setIsExecutingTodo(true);
      setExecutingTodoId(todoId);

      // Build the message the agent will execute
      const taskMessage =
        `Execute this todo for me: ${todo.title}` +
        (todo.description ? `\n\nContext: ${todo.description}` : "");

      setData((prev) => ({
        ...prev,
        executedTodoId: todoId,
        todoExecutionResult: taskMessage,
      }));

      // Transition to chat — the chat hook will auto-send this message
      setStep({ type: "chat" });
      void apiService.post("/onboarding/phase", { phase: "getting_started" });
    },
    [isExecutingTodo],
  );

  // Tracked so we can cancel the popup-close watcher on unmount.
  const popupCleanupRef = useRef<(() => void) | null>(null);

  const connectPlatform = useCallback(
    async (platform: string) => {
      // Cancel any prior in-flight popup watcher.
      popupCleanupRef.current?.();
      popupCleanupRef.current = null;

      const finish = () => {
        setData((prev) => ({ ...prev, connectedPlatform: platform }));
        advanceToChat();
      };

      try {
        const response = await apiService.get<{
          auth_url: string | null;
          auth_type: string;
          instructions: string | null;
          action_link: string | null;
        }>(`/platform-links/${platform.toLowerCase()}/connect`, {
          silent: true,
        });

        if (response.auth_url) {
          const width = 600;
          const height = 700;
          const left = window.screenX + (window.innerWidth - width) / 2;
          const top = window.screenY + (window.innerHeight - height) / 2;

          const popup = window.open(
            response.auth_url,
            `Connect ${platform}`,
            `width=${width},height=${height},left=${left},top=${top}`,
          );

          if (!popup) {
            finish();
            return;
          }

          // Detect popup closure via the only reliable signal cross-origin:
          // an rAF loop checking `popup.closed`. Properly torn down on
          // unmount or when the user re-triggers connect.
          let cancelled = false;
          let rafId = 0;
          const onMessage = (event: MessageEvent) => {
            if (event.source === popup) {
              cleanup();
              finish();
            }
          };
          const cleanup = () => {
            cancelled = true;
            if (rafId) cancelAnimationFrame(rafId);
            window.removeEventListener("message", onMessage);
            popupCleanupRef.current = null;
          };
          const tick = () => {
            if (cancelled) return;
            if (popup.closed) {
              cleanup();
              finish();
              return;
            }
            rafId = requestAnimationFrame(tick);
          };
          window.addEventListener("message", onMessage);
          rafId = requestAnimationFrame(tick);
          popupCleanupRef.current = cleanup;
        } else if (response.action_link) {
          window.open(response.action_link, "_blank");
          finish();
        }
      } catch {
        finish();
      }
    },
    [advanceToChat],
  );

  // Cancel any popup watcher on unmount.
  useEffect(() => {
    return () => {
      popupCleanupRef.current?.();
      popupCleanupRef.current = null;
    };
  }, []);

  const skipPlatformConnect = useCallback(() => {
    advanceToChat();
  }, [advanceToChat]);

  const reset = useCallback(() => {
    popupCleanupRef.current?.();
    popupCleanupRef.current = null;
    setStep({ type: "question", index: 0 });
    setData(INITIAL_DATA);
    setLoadingStatuses([]);
    setInboxScanCount(0);
    setCompletedStages(new Set());
    setRevealPhase("writing_style");
    setIsWaitingForNextPhase(false);
    setIsExecutingTodo(false);
    setExecutingTodoId(null);
    setCompletedTodoIds(new Set());
    intelligenceCompleteRef.current = false;
    // dataRef resets automatically via data state
  }, []);

  return {
    step,
    data,
    loadingStatuses,
    inboxScanCount,
    completedStages,
    isExecutingTodo,
    executingTodoId,
    completedTodoIds,
    revealPhase,
    isWaitingForNextPhase,
    advanceRevealPhase,
    advanceToWorkflows,
    advanceToChat,
    executeTodo,
    connectPlatform,
    skipPlatformConnect,
    handleStageEvent,
    handlePersonalizationComplete,
    handleIntelligenceComplete,
    reset,
  };
}
