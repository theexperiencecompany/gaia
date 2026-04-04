"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiService } from "@/lib/api/service";

import type { PersonalizationData } from "../types/websocket";

// ── Step State Machine ───────────────────────────────────────────────────────

export type OnboardingStep =
  | { type: "question"; index: number }
  | { type: "loading" }
  | { type: "todos" }
  | { type: "workflows_and_connect" }
  | { type: "chat" };

export type RevealPhase =
  | "writing_style"
  | "social_profiles"
  | "triage"
  | "todos"
  | "complete";

export interface OnboardingFlowData {
  todos: Array<{
    id: string;
    title: string;
    description?: string;
    source_email?: { sender: string; subject: string };
  }>;
  workflows: Array<{ id?: string; title: string; description?: string }>;
  triageSummary: {
    total_scanned: number;
    total_unread: number;
    summary?: string;
    patterns?: string[];
    important_emails: Array<{
      sender: string;
      subject: string;
      why_important: string;
    }>;
  } | null;
  writingStyle: { style_summary: string; sample_snippets?: string[] } | null;
  socialProfiles: Array<{ platform: string; url: string }>;
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
  progress: number;
  stageMessages: Record<string, string>;
  completedStages: Set<string>;
  isExecutingTodo: boolean;
  executingTodoId: string | null;
  completedTodoIds: Set<string>;
  revealPhase: RevealPhase;
  advanceRevealPhase: () => void;
  advanceToWorkflows: () => void;
  advanceToChat: () => void;
  executeTodo: (todoId: string) => void;
  handleTodoExecutionEvent: (
    todoId: string,
    status: string,
    result?: string,
  ) => void;
  connectPlatform: (platform: string) => void;
  skipPlatformConnect: () => void;
  handleProgressEvent: (
    stage: string,
    message: string,
    progress: number,
    results?: Record<string, unknown>,
  ) => void;
  handlePersonalizationComplete: (data: PersonalizationData) => void;
  handleIntelligenceComplete: (conversationId: string) => void;
  reset: () => void;
}

const INITIAL_DATA: OnboardingFlowData = {
  todos: [],
  workflows: [],
  triageSummary: null,
  writingStyle: null,
  socialProfiles: [],
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
  const [progress, setProgress] = useState(0);
  const [stageMessages, setStageMessages] = useState<Record<string, string>>(
    {},
  );
  const [completedStages, setCompletedStages] = useState<Set<string>>(
    new Set(),
  );
  const [revealPhase, setRevealPhase] = useState<RevealPhase>("writing_style");
  const [isExecutingTodo, setIsExecutingTodo] = useState(false);
  const [executingTodoId, setExecutingTodoId] = useState<string | null>(null);
  const [completedTodoIds, setCompletedTodoIds] = useState<Set<string>>(
    new Set(),
  );

  const intelligenceCompleteRef = useRef(false);
  const todosReadyRef = useRef(false);

  // Transition to loading step when processing phase starts
  useEffect(() => {
    if (isProcessingPhase && step.type === "question") {
      setStep({ type: "loading" });
    }
  }, [isProcessingPhase, step.type]);

  const handleProgressEvent = useCallback(
    (
      stage: string,
      message: string,
      progressValue: number,
      results?: Record<string, unknown>,
    ) => {
      setProgress((prev) => Math.max(prev, progressValue));

      if (message) {
        setLoadingStatuses((prev) => [
          ...prev,
          { message, timestamp: Date.now() },
        ]);
      }

      // Track latest message per stage for the processing step indicator
      if (stage && message) {
        setStageMessages((prev) => ({ ...prev, [stage]: message }));
      }

      // Mark stage as completed only when the backend sends results
      if (stage && results) {
        setCompletedStages((prev) => new Set([...prev, stage]));
      }

      if (!results) return;

      // Accumulate data from pipeline stages
      switch (stage) {
        case "scanning_inbox":
          break;
        case "triaging":
          if ("total_scanned" in results) {
            setData((prev) => ({
              ...prev,
              triageSummary: {
                total_scanned: results.total_scanned as number,
                total_unread: results.total_unread as number,
                summary: (results.summary as string) ?? "",
                patterns: (results.patterns as string[]) ?? [],
                important_emails: (results.important_emails ?? []) as Array<{
                  sender: string;
                  subject: string;
                  why_important: string;
                }>,
              },
            }));
          }
          break;
        case "creating_todos":
          if ("todos" in results && Array.isArray(results.todos)) {
            const todos = results.todos as Array<{
              id: string;
              title: string;
              source_email?: { sender: string; subject: string };
            }>;
            if (todos.length > 0) {
              todosReadyRef.current = true;
              setData((prev) => ({ ...prev, todos }));
              // Advance to todos immediately — don't wait for the full pipeline
              setStep((prev) =>
                prev.type === "loading" ? { type: "todos" } : prev,
              );
            }
          }
          break;
        case "creating_workflows":
          if ("workflows" in results && Array.isArray(results.workflows)) {
            setData((prev) => ({
              ...prev,
              workflows: results.workflows as Array<{
                id?: string;
                title: string;
                description?: string;
              }>,
            }));
          }
          break;
        case "learning_style":
          if ("style_summary" in results) {
            setData((prev) => ({
              ...prev,
              writingStyle: {
                style_summary: results.style_summary as string,
                sample_snippets: Array.isArray(results.sample_snippets)
                  ? (results.sample_snippets as string[])
                  : undefined,
              },
            }));
          }
          break;
        case "finding_profiles":
          if ("profiles" in results && Array.isArray(results.profiles)) {
            setData((prev) => ({
              ...prev,
              socialProfiles: results.profiles as Array<{
                platform: string;
                url: string;
              }>,
            }));
          }
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

    // If still on loading (no todos were created), skip to workflows
    setStep((prev) =>
      prev.type === "loading" ? { type: "workflows_and_connect" } : prev,
    );
  }, []);

  const advanceRevealPhase = useCallback(() => {
    setRevealPhase((prev) => {
      const order: RevealPhase[] = [
        "writing_style",
        "social_profiles",
        "triage",
        "todos",
        "complete",
      ];
      const currentIdx = order.indexOf(prev);
      for (let i = currentIdx + 1; i < order.length; i++) {
        const next = order[i];
        if (next === "writing_style" && !data.writingStyle) continue;
        if (next === "social_profiles" && data.socialProfiles.length === 0)
          continue;
        if (next === "triage" && !data.triageSummary) continue;
        if (next === "todos" && data.todos.length === 0) continue;
        return next;
      }
      return "complete";
    });
  }, [data]);

  const advanceToWorkflows = useCallback(() => {
    setStep({ type: "workflows_and_connect" });
  }, []);

  const advanceToChat = useCallback(() => {
    setStep({ type: "chat" });

    // Update backend phase
    void apiService.post("/onboarding/phase", { phase: "getting_started" });
  }, []);

  const executeTodo = useCallback(
    async (todoId: string) => {
      if (isExecutingTodo) return;
      setIsExecutingTodo(true);
      setExecutingTodoId(todoId);

      try {
        await apiService.post("/onboarding/execute-todo", {
          todo_id: todoId,
        });
        // Execution started in background — WebSocket events will
        // drive completion via handleTodoExecutionEvent below.
      } catch {
        // On failure, reset state so user can retry
        setIsExecutingTodo(false);
        setExecutingTodoId(null);
      }
    },
    [isExecutingTodo],
  );

  // Called by the page when a todo execution WebSocket event arrives
  const handleTodoExecutionEvent = useCallback(
    (todoId: string, status: string, result?: string) => {
      if (status === "completed" || status === "failed") {
        setCompletedTodoIds((prev) => new Set([...prev, todoId]));
        setIsExecutingTodo(false);
        setExecutingTodoId(null);
        setData((prev) => ({
          ...prev,
          executedTodoId: todoId,
          todoExecutionResult: result ?? null,
        }));

        // Auto-advance to workflows after 2s
        setTimeout(() => {
          setStep({ type: "workflows_and_connect" });
        }, 2000);
      }
    },
    [],
  );

  const connectPlatform = useCallback(
    async (platform: string) => {
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
          // OAuth flow — open popup
          const width = 600;
          const height = 700;
          const left = window.screenX + (window.innerWidth - width) / 2;
          const top = window.screenY + (window.innerHeight - height) / 2;

          const popup = window.open(
            response.auth_url,
            `Connect ${platform}`,
            `width=${width},height=${height},left=${left},top=${top}`,
          );

          // Poll for popup close
          const poll = setInterval(() => {
            if (popup?.closed) {
              clearInterval(poll);
              setData((prev) => ({ ...prev, connectedPlatform: platform }));
              setTimeout(() => advanceToChat(), 1500);
            }
          }, 500);
        } else if (response.action_link) {
          // Manual flow (Telegram) — open bot link in new tab
          window.open(response.action_link, "_blank");
          setData((prev) => ({ ...prev, connectedPlatform: platform }));
          setTimeout(() => advanceToChat(), 2000);
        }
      } catch {
        // If platform not configured, just record preference and move on
        setData((prev) => ({ ...prev, connectedPlatform: platform }));
        setTimeout(() => advanceToChat(), 1500);
      }
    },
    [advanceToChat],
  );

  const skipPlatformConnect = useCallback(() => {
    advanceToChat();
  }, [advanceToChat]);

  const reset = useCallback(() => {
    setStep({ type: "question", index: 0 });
    setData(INITIAL_DATA);
    setLoadingStatuses([]);
    setProgress(0);
    setStageMessages({});
    setCompletedStages(new Set());
    setRevealPhase("writing_style");
    setIsExecutingTodo(false);
    setExecutingTodoId(null);
    setCompletedTodoIds(new Set());
    intelligenceCompleteRef.current = false;
    todosReadyRef.current = false;
  }, []);

  return {
    step,
    data,
    loadingStatuses,
    progress,
    stageMessages,
    completedStages,
    isExecutingTodo,
    executingTodoId,
    completedTodoIds,
    revealPhase,
    advanceRevealPhase,
    advanceToWorkflows,
    advanceToChat,
    executeTodo,
    handleTodoExecutionEvent,
    connectPlatform,
    skipPlatformConnect,
    handleProgressEvent,
    handlePersonalizationComplete,
    handleIntelligenceComplete,
    reset,
  };
}
