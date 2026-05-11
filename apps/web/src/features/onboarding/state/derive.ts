/**
 * Linear stage cursor. The flow is a fixed queue of stages; the user
 * advances forward only, never sideways. Each stage has two checks:
 *
 * - `isStageReady` — does the backend have the data for this stage yet?
 * - `isStageDone`  — is the user past this stage (either acked, or the
 *   backend told us there is nothing to show here)?
 *
 * `getStage` walks the queue once and returns the first stage that is not
 * done. If that stage isn't ready, we render `processing` instead of
 * skipping ahead — this is what prevents an out-of-order event from
 * teleporting the user to a later stage.
 *
 * The queue is picked once from `hasGmail`: the no-Gmail branch literally
 * has no writing-style reveal, so we don't include it.
 */

import { FIELD_NAMES, questions } from "../constants";
import type { OnboardingStage } from "../types/websocket";
import type { OnboardingState, Stage } from "./types";

export function hasGmail(s: OnboardingState): boolean {
  return s.responses[FIELD_NAMES.GMAIL] === "connected";
}

/**
 * The user skipped Gmail and hasn't yet answered the synthetic focus
 * question — the no-Gmail branch needs this hint before it can run.
 */
export function needsFocus(s: OnboardingState): boolean {
  return (
    s.responses[FIELD_NAMES.GMAIL] === "skipped" &&
    s.responses[FIELD_NAMES.FOCUS] == null
  );
}

/** All required answers (incl. focus when Gmail is skipped) are captured. */
export function isResponsesComplete(s: OnboardingState): boolean {
  return s.questionIndex >= questions.length && !needsFocus(s);
}

const GMAIL_QUEUE: readonly Stage[] = [
  "revealWriting",
  "revealTodos",
  "workflows",
  "platforms",
  "chat",
];

const NO_GMAIL_QUEUE: readonly Stage[] = [
  "revealTodos",
  "workflows",
  "platforms",
  "chat",
];

/**
 * True iff the backend has emitted the payload the stage needs to render.
 * Stages with no data dependency (`platforms`) are always ready.
 */
function isStageReady(s: OnboardingState, stage: Stage): boolean {
  // `platforms` has no data dependency — always reachable once the cursor
  // gets there, even before the initial REST snapshot lands.
  if (stage === "platforms") return true;
  const b = s.server;
  if (!b) return false;
  switch (stage) {
    case "revealWriting":
      return !!b.writing_style?.style_summary;
    case "revealTodos":
      return (b.onboarding_todos?.length ?? 0) > 0;
    case "workflows":
      return (b.suggested_workflows?.length ?? 0) > 0;
    case "chat":
      return !!b.first_message_conversation_id;
    default:
      return false;
  }
}

/**
 * True iff the cursor should move past this stage. Either the user has
 * acted on it, or the backend has told us there's nothing here to show
 * (the matching `*_ready` event landed without any payload data).
 *
 * `revealWriting` also waits for `revealTodos` to be ready before being
 * marked done — that preserves the "Looking for things I can help with…"
 * holding block on the writing-style card after the user clicks "Looks
 * good" but before the todos data has arrived.
 */
function isStageDone(s: OnboardingState, stage: Stage): boolean {
  const b = s.server;
  switch (stage) {
    case "revealWriting": {
      if (s.ackedWritingStyle && isStageReady(s, "revealTodos")) return true;
      // Backend confirmed there's no style to show (LLM failure).
      if (
        s.completedStages.has("writing_style_ready") &&
        !b?.writing_style?.style_summary
      ) {
        return true;
      }
      return false;
    }
    case "revealTodos": {
      if (s.ackedTodos) return true;
      // Backend confirmed there are no todos to show.
      if (
        s.completedStages.has("todos_ready") &&
        !b?.onboarding_todos?.length
      ) {
        return true;
      }
      return false;
    }
    case "workflows": {
      if (s.workflowsConfirmed) return true;
      // Backend confirmed there are no workflows to show.
      if (
        s.completedStages.has("workflows_ready") &&
        !b?.suggested_workflows?.length
      ) {
        return true;
      }
      return false;
    }
    case "platforms":
      return s.platformsConfirmed;
    case "chat":
      return false;
    default:
      return false;
  }
}

/**
 * Resolves the stage the page should render right now. Walks the user's
 * linear queue (gmail vs no-gmail), returning the first stage that isn't
 * done. If that stage's data isn't ready, returns `processing` so the
 * spinner / progress checklist takes over until the event arrives.
 */
export function getStage(s: OnboardingState): Stage {
  if (s.questionIndex < questions.length) return "questions";
  if (needsFocus(s)) return "focus";

  const queue = hasGmail(s) ? GMAIL_QUEUE : NO_GMAIL_QUEUE;

  for (const stage of queue) {
    if (isStageDone(s, stage)) continue;
    if (isStageReady(s, stage)) return stage;
    return "processing";
  }

  return "chat";
}

/**
 * Live progress message for the deepest still-running pipeline stage, or
 * `null` if none have emitted yet. Used by the writing-style reveal's
 * holding block while we wait for todos.
 */
const POST_WRITING_PROGRESS_STAGES: readonly OnboardingStage[] = [
  "workflows_creating",
  "todos_creating",
  "triage_analyzing",
];

export function getCurrentProgress(s: OnboardingState): string | null {
  for (const stage of POST_WRITING_PROGRESS_STAGES) {
    const value = s.progressByStage[stage];
    if (value) return value;
  }
  return null;
}

/** Step index per stage for the top progress bar; total is PROGRESS_TOTAL_STEPS. */
const STAGE_PROGRESS: Record<Stage, number> = {
  questions: 0,
  focus: 3,
  processing: 3,
  revealWriting: 4,
  revealTodos: 5,
  workflows: 6,
  platforms: 7,
  chat: 8,
};

export const PROGRESS_TOTAL_STEPS = 8;

/** Step index (0-based) for the top progress bar. Snaps to 0 during restart. */
export function getProgress(s: OnboardingState, stage: Stage): number {
  if (s.isRestarting) return 0;
  if (stage === "questions") return s.questionIndex;
  return STAGE_PROGRESS[stage];
}
