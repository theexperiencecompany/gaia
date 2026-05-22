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

export function needsFocus(s: OnboardingState): boolean {
  return (
    s.responses[FIELD_NAMES.GMAIL] === "skipped" &&
    s.responses[FIELD_NAMES.FOCUS] == null
  );
}

export function needsClarify(s: OnboardingState): boolean {
  if (s.responses[FIELD_NAMES.GMAIL] !== "skipped") return false;
  if (s.responses[FIELD_NAMES.FOCUS] == null) return false;
  return !s.clarifySubmitted;
}

export function isResponsesComplete(s: OnboardingState): boolean {
  return (
    s.questionIndex >= questions.length && !needsFocus(s) && !needsClarify(s)
  );
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

function isStageReady(s: OnboardingState, stage: Stage): boolean {
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

// revealWriting waits for revealTodos to be ready before it's marked done,
// preserving the holding block on the writing-style card after the user acks.
function isWritingStageDone(s: OnboardingState): boolean {
  if (s.ackedWritingStyle && isStageReady(s, "revealTodos")) return true;
  return (
    s.completedStages.has("writing_style_ready") &&
    !s.server?.writing_style?.style_summary
  );
}

function isTodosStageDone(s: OnboardingState): boolean {
  if (s.ackedTodos) return true;
  return (
    s.completedStages.has("todos_ready") && !s.server?.onboarding_todos?.length
  );
}

function isWorkflowsStageDone(s: OnboardingState): boolean {
  if (s.workflowsConfirmed) return true;
  return (
    s.completedStages.has("workflows_ready") &&
    !s.server?.suggested_workflows?.length
  );
}

function isStageDone(s: OnboardingState, stage: Stage): boolean {
  switch (stage) {
    case "revealWriting":
      return isWritingStageDone(s);
    case "revealTodos":
      return isTodosStageDone(s);
    case "workflows":
      return isWorkflowsStageDone(s);
    case "platforms":
      return s.platformsConfirmed;
    default:
      return false;
  }
}

export function getStage(s: OnboardingState): Stage {
  if (s.questionIndex < questions.length) return "questions";
  if (needsFocus(s)) return "focus";
  if (needsClarify(s)) return "clarify";

  const queue = hasGmail(s) ? GMAIL_QUEUE : NO_GMAIL_QUEUE;

  for (const stage of queue) {
    if (isStageDone(s, stage)) continue;
    if (isStageReady(s, stage)) return stage;
    return "processing";
  }

  return "chat";
}

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

const STAGE_PROGRESS: Record<Stage, number> = {
  questions: 0,
  focus: 3,
  clarify: 4,
  processing: 4,
  revealWriting: 5,
  revealTodos: 6,
  workflows: 7,
  platforms: 8,
  chat: 9,
};

export const PROGRESS_TOTAL_STEPS = 9;

export function getProgress(s: OnboardingState, stage: Stage): number {
  if (s.isRestarting) return 0;
  if (stage === "questions") return s.questionIndex;
  return STAGE_PROGRESS[stage];
}
