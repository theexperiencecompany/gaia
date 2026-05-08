/**
 * Pure selectors that derive UI-facing values from `OnboardingState` and the
 * server snapshot. `getStage` is the single source of truth for which stage
 * the page renders — never compute it ad-hoc in components.
 */

import { FIELD_NAMES, questions } from "../constants";
import type { OnboardingStage, PersonalizationData } from "../types/websocket";
import type { OnboardingState, Stage } from "./types";

/**
 * After writing-style ack, the still-running pipeline is one of these
 * stages. Listed in critical-path order — `pickFirst` returns the deepest
 * stage that currently has a status_text so the user always sees the most
 * advanced step's live update.
 */
const POST_WRITING_PROGRESS_STAGES: readonly OnboardingStage[] = [
  "workflows_creating",
  "todos_creating",
  "triage_analyzing",
];

/**
 * Returns the live progress message for the deepest still-running pipeline
 * stage, or `null` if none have emitted yet. Used by the writing-style
 * reveal's "looking for things I can help with" waiting block.
 */
export function getCurrentProgress(s: OnboardingState): string | null {
  for (const stage of POST_WRITING_PROGRESS_STAGES) {
    const value = s.progressByStage[stage];
    if (value) return value;
  }
  return null;
}

const PIPELINE_RUNNING_STATUSES: ReadonlySet<string> = new Set([
  "pending",
  "processing",
]);

/** True while the backend personalization DAG is still running. */
export function pipelineRunning(b: PersonalizationData): boolean {
  return b.bio_status != null && PIPELINE_RUNNING_STATUSES.has(b.bio_status);
}

/** True once the welcome conversation has been created server-side. */
export function pipelineDone(b: PersonalizationData): boolean {
  return b.first_message_conversation_id != null;
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

/**
 * Resolves the active stage from state. Precedence (top wins):
 * questions while Q&A unfinished → focus when Gmail was skipped without a
 * focus answer → processing while the pipeline runs or has no result yet →
 * revealWriting once writing-style is ready and not yet acked → revealTodos
 * once todos arrive and not yet acked → workflows once workflows or
 * conversation are ready and not yet confirmed → chat once the welcome
 * conversation exists. Falls back to processing.
 */
export function getStage(s: OnboardingState): Stage {
  if (s.questionIndex < questions.length) return "questions";
  if (needsFocus(s)) return "focus";

  const b = s.server;
  if (!b || pipelineRunning(b)) return "processing";

  if (
    b.writing_style?.style_summary &&
    (!s.ackedWritingStyle || (!b.onboarding_todos?.length && !pipelineDone(b)))
  ) {
    return "revealWriting";
  }

  if (b.onboarding_todos?.length && !s.ackedTodos) return "revealTodos";

  if (
    !s.workflowsConfirmed &&
    ((b.suggested_workflows?.length ?? 0) > 0 || pipelineDone(b))
  ) {
    return "workflows";
  }

  if (b.first_message_conversation_id) return "chat";

  return "processing";
}

/** Step index per stage for the top progress bar; total is PROGRESS_TOTAL_STEPS. */
const STAGE_PROGRESS: Record<Stage, number> = {
  questions: 0,
  focus: 3,
  processing: 3,
  revealWriting: 4,
  revealTodos: 4,
  workflows: 5,
  chat: 6,
};

export const PROGRESS_TOTAL_STEPS = 6;

/** Step index (0-based) for the top progress bar. Snaps to 0 during restart. */
export function getProgress(s: OnboardingState, stage: Stage): number {
  if (s.isRestarting) return 0;
  if (stage === "questions") return s.questionIndex;
  return STAGE_PROGRESS[stage];
}

/** True iff the user's Gmail answer is `connected` (vs `skipped`). */
export function hasGmail(s: OnboardingState): boolean {
  return s.responses[FIELD_NAMES.GMAIL] === "connected";
}
