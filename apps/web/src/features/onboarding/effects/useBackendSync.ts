/**
 * Drives the live backend connection during onboarding: fetches the initial
 * personalization snapshot via REST, opens a WebSocket for stage events, and
 * falls back to REST polling if the socket goes silent.
 */

"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { syncSingleConversation } from "@/services/syncService";
import { getPersonalization } from "../api/onboardingApi";
import type { Action, OnboardingState, Stage } from "../state/types";
import type {
  OnboardingStage,
  PersonalizationData,
  StagePayloads,
  WorkflowResults,
} from "../types/websocket";

type SuggestedWorkflows = NonNullable<
  PersonalizationData["suggested_workflows"]
>;

function mapSuggestedWorkflows(
  workflows: WorkflowResults["workflows"],
): SuggestedWorkflows {
  return workflows.map((w) => ({
    id: w.id ?? "",
    title: w.title,
    description: w.description ?? "",
    steps: (w.categories ?? []).map((c) => ({ category: c })),
    trigger: w.trigger,
  }));
}

const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY_MS = 1000;
const WS_SILENCE_FALLBACK_MS = 5000;
const POLL_INTERVAL_MS = 3000;

function getWsUrl(): string {
  const base =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1/";
  return (
    base.replace("http://", "ws://").replace("https://", "wss://") +
    "ws/connect"
  );
}

type StageEnvelope = {
  [K in OnboardingStage]: { stage: K; payload: StagePayloads[K] };
}[OnboardingStage];

export function useBackendSync(
  state: OnboardingState,
  stage: Stage,
  dispatch: Dispatch<Action>,
): void {
  const active =
    stage !== "questions" && stage !== "focus" && !state.isRestarting;

  const dispatchRef = useRef(dispatch);
  const isRestartingRef = useRef(state.isRestarting);

  useEffect(() => {
    dispatchRef.current = dispatch;
  });
  useEffect(() => {
    isRestartingRef.current = state.isRestarting;
  });

  useEffect(() => {
    if (!active) return;

    let aborted = false;
    let snapshotResolved = false;
    const buffer: StageEnvelope[] = [];
    let ws: WebSocket | null = null;
    let reconnectAttempts = 0;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let silenceTimer: ReturnType<typeof setTimeout> | null = null;
    let pollTimer: ReturnType<typeof setInterval> | null = null;
    let silenceFallbackUsed = false;
    let wsReceivedEvent = false;
    let closed = false;

    type StageHandlers = {
      [K in OnboardingStage]: (payload: StagePayloads[K]) => void;
    };

    const dispatchProgress = (
      stage: OnboardingStage,
      status_text: string | undefined,
    ): void => {
      if (!status_text) {
        console.warn(
          `[onboarding:ws] ${stage} progress event with no status_text — backend likely stale`,
        );
        return;
      }
      dispatchRef.current({ type: "progress", stage, message: status_text });
    };

    const handlers: StageHandlers = {
      inbox_scanning: (p) => dispatchProgress("inbox_scanning", p.status_text),
      writing_style_progress: (p) =>
        dispatchProgress("writing_style_progress", p.status_text),
      triage_analyzing: (p) =>
        dispatchProgress("triage_analyzing", p.status_text),
      todos_creating: (p) => dispatchProgress("todos_creating", p.status_text),
      workflows_creating: (p) =>
        dispatchProgress("workflows_creating", p.status_text),
      writing_style_ready: (p) => {
        // Backend may emit style_summary=null on learning failure to advance
        // the cursor; derive.ts treats null as "skip the reveal".
        const summary = p.style_summary?.trim();
        dispatchRef.current({
          type: "serverPatch",
          patch: {
            writing_style: summary
              ? { style_summary: summary, example: p.example ?? null }
              : null,
          },
        });
      },
      social_profiles_ready: (p) => {
        dispatchRef.current({
          type: "serverPatch",
          patch: { social_profiles: p.profiles },
        });
      },
      triage_ready: (p) => {
        dispatchRef.current({
          type: "serverPatch",
          patch: { triage_summary: p },
        });
      },
      todos_ready: (p) => {
        dispatchRef.current({
          type: "serverPatch",
          patch: { onboarding_todos: p.todos },
        });
      },
      workflows_ready: (p) => {
        dispatchRef.current({
          type: "serverPatch",
          patch: { suggested_workflows: mapSuggestedWorkflows(p.workflows) },
        });
      },
      holo_ready: () => {
        getPersonalization()
          .then((data) => {
            if (aborted || isRestartingRef.current) return;
            dispatchRef.current({ type: "serverSnapshot", data });
            dispatchRef.current({
              type: "stageComplete",
              stage: "holo_ready",
            });
          })
          .catch(() => {});
      },
      complete: (p) => {
        dispatchRef.current({
          type: "serverPatch",
          patch: {
            first_message_conversation_id: p.conversation_id ?? undefined,
            phase: "personalization_complete",
          },
        });
        // Prefetch the welcome conversation into IndexedDB so the post-
        // onboarding /c/{id} mount doesn't flash the generic starter.
        if (p.conversation_id) {
          void syncSingleConversation(p.conversation_id).catch(() => {});
        }
        closeWs();
      },
    };

    const dispatchEnvelope = <K extends OnboardingStage>(
      stage: K,
      payload: StagePayloads[K],
    ) => {
      handlers[stage](payload);
    };

    const handleStage = (envelope: StageEnvelope) => {
      if (aborted) return;
      if (isRestartingRef.current) return;

      if (envelope.stage !== "holo_ready") {
        dispatchRef.current({
          type: "stageComplete",
          stage: envelope.stage,
        });
      }
      dispatchEnvelope(envelope.stage, envelope.payload);
    };

    const flushBuffer = () => {
      while (buffer.length > 0) {
        const next = buffer.shift();
        if (next) handleStage(next);
      }
    };

    const stopPoll = () => {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    };

    const closeWs = () => {
      closed = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      if (silenceTimer) {
        clearTimeout(silenceTimer);
        silenceTimer = null;
      }
      stopPoll();
      if (ws) {
        ws.close();
        ws = null;
      }
    };

    const pollOnce = () => {
      if (closed || aborted || isRestartingRef.current) return;
      getPersonalization()
        .then((data) => {
          if (aborted || isRestartingRef.current) return;
          dispatchRef.current({ type: "serverSnapshot", data });
          synthesizeCompletedStages(data);
          if (data.first_message_conversation_id) stopPoll();
        })
        .catch(() => {});
    };

    const synthesizeCompletedStages = (data: PersonalizationData): void => {
      // Only fire when the snapshot carries real data; null/[] come back on
      // a fresh post-reset snapshot and must not mark a stage done.
      const fire = (stage: OnboardingStage) =>
        dispatchRef.current({ type: "stageComplete", stage });
      if (data.writing_style?.style_summary) fire("writing_style_ready");
      if (data.triage_summary) fire("triage_ready");
      if ((data.onboarding_todos?.length ?? 0) > 0) fire("todos_ready");
      if ((data.suggested_workflows?.length ?? 0) > 0) fire("workflows_ready");
      if ((data.social_profiles?.length ?? 0) > 0) {
        fire("social_profiles_ready");
      }
      if (data.first_message_conversation_id) fire("complete");
    };

    const startPolling = () => {
      if (pollTimer || closed || aborted || isRestartingRef.current) return;
      pollOnce();
      pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS);
    };

    const runSilenceFallback = () => {
      if (silenceFallbackUsed) return;
      if (wsReceivedEvent) return;
      if (closed || aborted || isRestartingRef.current) return;
      silenceFallbackUsed = true;
      startPolling();
    };

    const connectWs = () => {
      if (closed || aborted) return;
      try {
        const socket = new WebSocket(getWsUrl());
        ws = socket;

        socket.onopen = () => {
          const isReconnect = reconnectAttempts > 0;
          reconnectAttempts = 0;
          if (isReconnect) {
            // Close the gap with a fresh snapshot — events during the
            // disconnect window are lost.
            pollOnce();
          }
          if (
            !silenceFallbackUsed &&
            !wsReceivedEvent &&
            silenceTimer === null
          ) {
            silenceTimer = setTimeout(
              runSilenceFallback,
              WS_SILENCE_FALLBACK_MS,
            );
          }
        };

        socket.onmessage = (event) => {
          if (aborted || isRestartingRef.current) return;
          wsReceivedEvent = true;
          if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
          }
          stopPoll();
          try {
            const message = JSON.parse(event.data) as {
              type: string;
              data: unknown;
            };
            if (message.type !== "onboarding_stage") return;
            const envelope = message.data as StageEnvelope;
            console.debug("[onboarding:ws]", envelope.stage, envelope.payload);
            if (!snapshotResolved) {
              buffer.push(envelope);
              return;
            }
            handleStage(envelope);
          } catch (error) {
            console.error("[onboarding:ws] parse error:", error);
          }
        };

        socket.onclose = () => {
          ws = null;
          if (closed || aborted) return;
          if (reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            const delay =
              RECONNECT_BASE_DELAY_MS * 2 ** Math.min(reconnectAttempts, 5);
            reconnectAttempts += 1;
            reconnectTimer = setTimeout(connectWs, delay);
          }
        };

        socket.onerror = () => {};
      } catch {}
    };

    getPersonalization()
      .then((data) => {
        if (aborted) return;
        dispatchRef.current({ type: "serverSnapshot", data });
        synthesizeCompletedStages(data);
        snapshotResolved = true;
        flushBuffer();
      })
      .catch(() => {
        snapshotResolved = true;
        flushBuffer();
      });

    connectWs();

    return () => {
      aborted = true;
      closeWs();
    };
  }, [active]);
}
