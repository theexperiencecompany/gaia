/**
 * Onboarding state shape and the discriminated union of actions the reducer
 * accepts. The reducer is the single mutation point; every effect/component
 * dispatches into it. Keep this file authoritative for what the flow
 * remembers and how it can change.
 */

import type {
  OnboardingStage,
  PersonalizationData,
  StagePayloads,
} from "../types/websocket";

/**
 * Derived stage label rendered by the page. See `getStage` in `derive.ts`
 * for the precedence rules — components should never compute this themselves.
 */
export type Stage =
  | "questions"
  | "focus"
  | "processing"
  | "revealWriting"
  | "revealTodos"
  | "workflows"
  | "chat";

export interface OnboardingState {
  /** Answered Q&A keyed by FIELD_NAMES (name, profession, gmail, focus). */
  responses: Record<string, string>;
  /** Index into `questions[]`; equals questions.length once Q&A is finished. */
  questionIndex: number;
  /** In-flight text input value for the active text question. */
  draftText: string;
  /** In-flight Autocomplete value for the profession question. */
  draftProfession: string | null;

  /** Latest server-side personalization snapshot (REST + WS-merged). */
  server: PersonalizationData | null;

  /** Live status text from the backend (e.g. "200 emails fetched"). */
  progressMessage: string | null;
  /** Set of pipeline stages that have emitted a completion event. */
  completedStages: Set<OnboardingStage>;

  /** User confirmed the writing-style reveal card. */
  ackedWritingStyle: boolean;
  /** User confirmed (or skipped) the todos reveal card. */
  ackedTodos: boolean;

  /** User confirmed the workflows step (with or without a platform connect). */
  workflowsConfirmed: boolean;
  /** Messaging platform the user linked during the workflows step, if any. */
  connectedPlatform: string | null;

  /** Pending todo to auto-send into the chat conversation once it's ready. */
  todoExecutionMessage: string | null;

  /** POST /onboarding failed; the processing composer offers a retry. */
  submissionError: boolean;
  /** Restart in progress — UI is locked while the server `/reset` runs. */
  isRestarting: boolean;
}

export type Action =
  /** Live-update the active text question's draft input. */
  | { type: "draftText"; value: string }
  /** Live-update the profession Autocomplete draft. */
  | { type: "draftProfession"; value: string | null }
  /** User submitted an answer; advances `questionIndex`. */
  | { type: "answer"; field: string; value: string }
  /** POST /onboarding failed; arms the retry composer. */
  | { type: "submitError" }
  /** User clicked retry on the submission error composer. */
  | { type: "retrySubmit" }
  /** Full personalization snapshot from REST (poll or initial fetch). */
  | { type: "serverSnapshot"; data: PersonalizationData }
  /** Partial patch from a WS stage event. */
  | {
      type: "serverPatch";
      patch: Partial<PersonalizationData>;
    }
  /** Live status string from the active backend stage. */
  | { type: "progress"; message: string | null }
  /** A backend stage finished — used to drive the processing checklist. */
  | { type: "stageComplete"; stage: OnboardingStage }
  /** User confirmed the writing-style reveal card. */
  | { type: "ackWriting" }
  /** User confirmed (or skipped) the todos reveal card. */
  | { type: "ackTodos" }
  /** User confirmed the workflows step without connecting a platform. */
  | { type: "confirmWorkflows" }
  /** User finished the platform-connect popup flow. */
  | { type: "platformConnected"; platform: string }
  /** User clicked Run on a todo; queues the message for the chat stage. */
  | { type: "executeTodo"; message: string }
  /** Chat stage consumed the pending todo execution message. */
  | { type: "clearTodoExecutionMessage" }
  /** Restart kicked off — flips state back to initial and locks UI. */
  | { type: "restartStart" }
  /** Server `/reset` settled (success or fail); unlocks UI. */
  | { type: "restartDone" }
  /** Hydrate from sessionStorage (or backend resume) on mount. */
  | { type: "hydrate"; partial: Partial<OnboardingState> }
  /** Hard reset to `initialState` (test/debug). */
  | { type: "reset" };

export type StagePayload<K extends OnboardingStage> = StagePayloads[K];
