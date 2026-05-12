/**
 * Drives the live backend connection during onboarding: fetches the initial
 * personalization snapshot via REST, opens a WebSocket for stage events, and
 * falls back to REST polling if the socket goes silent.
 */

"use client";

import { type Dispatch, useEffect, useRef } from "react";

import { getPersonalization } from "../api/onboardingApi";
import type { Action, OnboardingState, Stage } from "../state/types";
import type {
  OnboardingStage,
  PersonalizationData,
  StagePayloads,
} from "../types/websocket";

const MAX_RECONNECT_ATTEMPTS = 10;
const RECONNECT_BASE_DELAY_MS = 1000;
// If the WS connects but stays silent past this window, kick off a REST
// poll so the user isn't stuck behind a silent socket.
const WS_SILENCE_FALLBACK_MS = 5000;
// Once polling, refetch the snapshot at this cadence. Cleared the moment
// any WS event lands.
const POLL_INTERVAL_MS = 3000;

function getWsUrl(): string {
  const base =
    process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1/";
  return (
    base.replace("http://", "ws://").replace("https://", "wss://") +
    "ws/connect"
  );
}

/**
 * Discriminated-union envelope: narrowing on `stage` automatically narrows
 * `payload`, so handlers can be typed without per-case `as` casts.
 */
type StageEnvelope = {
  [K in OnboardingStage]: { stage: K; payload: StagePayloads[K] };
}[OnboardingStage];

/**
 * Activates once the user is past Q&A/focus. Fetches `/personalization`
 * once, then routes WS `onboarding_stage` events into reducer dispatches.
 * If the socket connects but stays silent for `WS_SILENCE_FALLBACK_MS`,
 * starts polling `/personalization` every `POLL_INTERVAL_MS` until the WS
 * sends an event or a snapshot with a conversation id arrives. Reconnects
 * with exponential backoff up to MAX_RECONNECT_ATTEMPTS.
 */
export function useBackendSync(
  state: OnboardingState,
  stage: Stage,
  dispatch: Dispatch<Action>,
): void {
  // Active once we've moved past the Q&A composer stages.
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
        // For Gmail users where learning failed (LLM error, near-zero sent
        // emails) the backend still emits with style_summary=null so the
        // cursor can advance. Combined with `completedStages.has(
        // "writing_style_ready")`, derive.ts treats this as "skip the
        // reveal" instead of leaving the user stuck.
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
          patch: {
            suggested_workflows: p.workflows.map((w) => ({
              id: w.id ?? "",
              title: w.title,
              description: w.description ?? "",
              steps: (w.categories ?? []).map((c) => ({ category: c })),
              trigger: w.trigger,
            })),
          },
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
          .catch(() => {
            // swallow — WS reconnect or poll will retry
          });
      },
      complete: (p) => {
        // Backend emits `complete` only after holo_ready has fired (holo
        // card now runs inside the main pipeline gather), so closing the WS
        // here is safe — no terminal events trail this one.
        dispatchRef.current({
          type: "serverPatch",
          patch: {
            first_message_conversation_id: p.conversation_id ?? undefined,
            phase: "personalization_complete",
          },
        });
        closeWs();
      },
    };

    /**
     * Calls the right handler for an envelope. Generic so TS narrows
     * `StagePayloads[K]` against `K` — no per-case `as` casts needed.
     */
    const dispatchEnvelope = <K extends OnboardingStage>(
      stage: K,
      payload: StagePayloads[K],
    ) => {
      handlers[stage](payload);
    };

    const handleStage = (envelope: StageEnvelope) => {
      if (aborted) return;
      if (isRestartingRef.current) return;

      // holo_ready dispatches stageComplete itself once the REST follow-up
      // resolves; everything else marks complete synchronously here.
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
          // The snapshot fills server-side data but `completedStages` is a
          // session-local Set that only the WS handler populates. Backfill
          // it from the snapshot so the processing checklist marks rows done
          // even when the matching event was lost during a WS disconnect.
          synthesizeCompletedStages(data);
          if (data.first_message_conversation_id) stopPoll();
        })
        .catch(() => {
          // keep polling — WS may still recover
        });
    };

    const synthesizeCompletedStages = (data: PersonalizationData): void => {
      // Only fire when the snapshot carries actual data — `null` and `[]`
      // come back on a fresh post-reset snapshot and must not be mistaken
      // for "the pipeline already finished this step".
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
            // Any stage event emitted during the disconnect window is gone
            // — close the gap with a fresh REST snapshot so the cursor can
            // catch up to whatever the pipeline reached while we were down.
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

        socket.onerror = () => {
          // onclose handles reconnect
        };
      } catch {
        // constructor failed
      }
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
