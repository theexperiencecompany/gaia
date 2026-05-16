"use client";

import { useEffect, useRef } from "react";

import type { UserInfo } from "@/features/auth/api/authApi";
import { useUserStore } from "@/stores/userStore";

import { completeOnboarding } from "../api/onboardingApi";
import { FIELD_NAMES } from "../constants";
import { isResponsesComplete } from "../state/derive";
import type { OnboardingState } from "../state/types";

/**
 * Fires POST /onboarding once all required answers are captured and the
 * pipeline hasn't started yet. Idempotent via an in-flight ref *and* the
 * persisted `user.onboarding.completed` flag — the in-flight ref alone is
 * insufficient because any remount (OAuth bounce, back-nav from /c/{id},
 * manual refresh) creates a fresh ref while `state.server` is still null
 * until `useBackendSync`'s async snapshot fetch resolves. Without the
 * persisted guard, the user-store flag wins that race and a duplicate POST
 * fires, re-running the intelligence pipeline.
 *
 * The snapshot-based guard only bails when the snapshot reports a phase past
 * `"initial"`. A bare `state.server != null` check would trap the no-Gmail
 * path: `useBackendSync` activates at `"clarify"` and resolves the initial
 * snapshot before the user finishes answering, so by submit time `server`
 * is non-null but the pipeline has not started yet. The phase check matches
 * the original intent ("pipeline already running") without the false bail.
 */
export function useOnboardingSubmission(
  state: OnboardingState,
  onSuccess?: (user: UserInfo) => void,
): void {
  const inFlightRef = useRef(false);
  const alreadyCompleted = useUserStore(
    (s) => s.onboarding?.completed === true,
  );

  useEffect(() => {
    if (inFlightRef.current) {
      console.debug("[onboarding:submit] skip — inFlight");
      return;
    }
    if (state.isRestarting) {
      console.debug("[onboarding:submit] skip — isRestarting");
      return;
    }
    const serverPhase = state.server?.phase;
    if (serverPhase && serverPhase !== "initial") {
      console.debug("[onboarding:submit] skip — phase", serverPhase);
      return;
    }
    if (alreadyCompleted) {
      console.debug("[onboarding:submit] skip — alreadyCompleted");
      return;
    }
    if (!isResponsesComplete(state)) {
      console.debug("[onboarding:submit] skip — responses incomplete", {
        questionIndex: state.questionIndex,
        gmail: state.responses?.gmail,
        focus: state.responses?.focus,
        clarifySubmitted: state.clarifySubmitted,
      });
      return;
    }
    console.debug("[onboarding:submit] FIRING POST /onboarding");

    inFlightRef.current = true;
    const responses = state.responses;
    // Clarify follow-up answers only exist on the no-Gmail path. Skipped
    // answers are dropped server-side so we don't pre-filter here — the
    // backend keeps things explicit by storing only non-null values.
    const clarifyAnswers = state.clarifyQuestions
      ? state.clarifyQuestions.map((q) => {
          const a = state.clarifyAnswers[q.id];
          return {
            id: q.id,
            kind: q.kind,
            question: q.question,
            value:
              a?.kind === "option" || a?.kind === "custom" ? a.value : null,
          };
        })
      : undefined;
    const body = {
      name: responses[FIELD_NAMES.NAME]?.trim() ?? "",
      profession: responses[FIELD_NAMES.PROFESSION] ?? "",
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      focus: responses[FIELD_NAMES.FOCUS] ?? "",
      ...(clarifyAnswers ? { clarify_answers: clarifyAnswers } : {}),
    };

    completeOnboarding(body)
      .then((response) => {
        if (response?.success && response.user) {
          onSuccess?.(response.user);
        }
      })
      .catch(() => {
        // Submission failed; processing stage stays as-is.
      })
      .finally(() => {
        inFlightRef.current = false;
      });
  }, [state, onSuccess, alreadyCompleted]);
}
