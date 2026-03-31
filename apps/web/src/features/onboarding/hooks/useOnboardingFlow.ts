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

export interface OnboardingFlowData {
  todos: Array<{ id: string; title: string; description?: string }>;
  workflows: Array<{ id?: string; title: string; description?: string }>;
  triageSummary: {
    total_scanned: number;
    total_unread: number;
    important_emails: Array<{
      sender: string;
      subject: string;
      why_important: string;
    }>;
  } | null;
  writingStyle: { style_summary: string } | null;
  socialProfiles: Array<{ platform: string; url: string }>;
  holoCardData: PersonalizationData | null;
  conversationId: string | null;
  connectedPlatform: string | null;
  executedTodoId: string | null;
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
  isExecutingTodo: boolean;
  executingTodoId: string | null;
  completedTodoIds: Set<string>;
  advanceToTodos: () => void;
  advanceToWorkflows: () => void;
  advanceToChat: () => void;
  executeTodo: (todoId: string) => void;
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

  // Auto-transition from loading → todos when data is ready
  useEffect(() => {
    if (
      step.type === "loading" &&
      intelligenceCompleteRef.current &&
      todosReadyRef.current
    ) {
      setStep({ type: "todos" });
    }
  }, [step.type, data.todos]);

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
            }>;
            if (todos.length > 0) {
              todosReadyRef.current = true;
              setData((prev) => ({ ...prev, todos }));
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

    // If we have todos, auto-advance from loading
    if (todosReadyRef.current) {
      setStep({ type: "todos" });
    } else {
      // No todos — skip to workflows or chat
      todosReadyRef.current = true;
      setStep({ type: "workflows_and_connect" });
    }
  }, []);

  const advanceToTodos = useCallback(() => {
    setStep({ type: "todos" });
  }, []);

  const advanceToWorkflows = useCallback(() => {
    setStep({ type: "workflows_and_connect" });
  }, []);

  const advanceToChat = useCallback(() => {
    setStep({ type: "chat" });

    // Update backend phase
    void apiService.post("/onboarding/phase", { phase: "getting_started" });
  }, []);

  const executeTodo = useCallback(
    (todoId: string) => {
      if (isExecutingTodo) return;
      setIsExecutingTodo(true);
      setExecutingTodoId(todoId);

      // Simulate execution (the real endpoint will be called by the agent)
      // For now, mark as completed after a brief period
      setTimeout(() => {
        setCompletedTodoIds((prev) => new Set([...prev, todoId]));
        setIsExecutingTodo(false);
        setExecutingTodoId(null);
        setData((prev) => ({ ...prev, executedTodoId: todoId }));

        // Auto-advance to workflows after 2s
        setTimeout(() => {
          setStep({ type: "workflows_and_connect" });
        }, 2000);
      }, 3000);
    },
    [isExecutingTodo],
  );

  const connectPlatform = useCallback(
    (platform: string) => {
      setData((prev) => ({ ...prev, connectedPlatform: platform }));

      // Auto-advance to chat after a brief delay
      setTimeout(() => {
        advanceToChat();
      }, 1500);
    },
    [advanceToChat],
  );

  const skipPlatformConnect = useCallback(() => {
    advanceToChat();
  }, [advanceToChat]);

  return {
    step,
    data,
    loadingStatuses,
    progress,
    isExecutingTodo,
    executingTodoId,
    completedTodoIds,
    advanceToTodos,
    advanceToWorkflows,
    advanceToChat,
    executeTodo,
    connectPlatform,
    skipPlatformConnect,
    handleProgressEvent,
    handlePersonalizationComplete,
    handleIntelligenceComplete,
  };
}
