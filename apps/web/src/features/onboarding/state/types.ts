/**
 * Onboarding state shape and the discriminated union of actions the reducer
 * accepts. The reducer is the single mutation point; every effect/component
 * dispatches into it. Keep this file authoritative for what the flow
 * remembers and how it can change.
 */

import type { ClarifyAnswer, ClarifyQuestion } from "../types";
import type {
  OnboardingStage,
  PersonalizationData,
  StagePayloads,
} from "../types/websocket";

/**
 * Linear stage queue rendered by the page. Each stage advances forward only,
 * driven by either a user action (ack / confirm) or a backend "no data, skip"
 * signal. `getStage` walks the queue once per render — components should
 * never compute this themselves.
 */
export type Stage =
  | "questions"
  | "focus"
  | "clarify"
  | "processing"
  | "revealWriting"
  | "revealTodos"
  | "workflows"
  | "platforms"
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

  /**
   * Live status text from the backend, scoped per stage so a late
   * progress event from one stage cannot bleed into the visible label of
   * another. Keyed by the emitting `OnboardingStage`.
   */
  progressByStage: Partial<Record<OnboardingStage, string>>;
  /** Set of pipeline stages that have emitted a completion event. */
  completedStages: Set<OnboardingStage>;

  /** User confirmed the writing-style reveal card. */
  ackedWritingStyle: boolean;
  /** User confirmed (or skipped) the todos reveal card. */
  ackedTodos: boolean;

  /** User clicked "Understood" on the workflows reveal card. */
  workflowsConfirmed: boolean;
  /** User finished the platform-connect step — either connected or skipped. */
  platformsConfirmed: boolean;
  /** Messaging platform the user linked during the platforms stage, if any. */
  connectedPlatform: string | null;

  /** Pending todo to auto-send into the chat conversation once it's ready. */
  todoExecutionMessage: string | null;
  /**
   * Throwaway conversation id the run-now demo streams into. Generated fresh
   * on every Run-Now click so the demo never bleeds into the welcome
   * conversation (which the user lands in after "Continue to GAIA").
   */
  todoExecutionConvoId: string | null;
  /**
   * User clicked Run on a todo. The `revealTodos` stage swaps its todo grid
   * for the chat stream in-place; the stage stays active until the user
   * dispatches `ackTodoDemo` from the post-demo Continue button.
   */
  todoExecutionStarted: boolean;
  /**
   * The todo the user clicked Run on. Surfaced as a static "selected todo"
   * indicator at the top of the demo container — the raw auto-sent user
   * message itself is hidden from the stream.
   */
  todoExecutionTodo: {
    id: string;
    title: string;
    sourceEmail: { sender: string; subject: string } | null;
  } | null;

  /** Restart in progress — UI is locked while the server `/reset` runs. */
  isRestarting: boolean;

  /**
   * No-Gmail clarify stage. The 3 LLM-generated follow-up questions asked
   * after the focus answer so the todo generator has scope/blocker/constraint
   * signal. `null` means we haven't fetched them yet; an empty array would
   * mean the backend declined to ask any.
   */
  clarifyQuestions: ClarifyQuestion[] | null;
  /** Per-question answer, keyed by question id. Missing key = not yet answered. */
  clarifyAnswers: Record<string, ClarifyAnswer>;
  /** Active tab in the clarify composer; defaults to the first question id. */
  clarifyActiveTab: string | null;
  /** In-flight custom text inputs per question id (reveals when "Other" is chosen). */
  clarifyCustomDrafts: Record<string, string>;
  /**
   * Per-question flag: did the user pick the "Other" radio? Tracked separately
   * from `clarifyCustomDrafts` so selection (radio highlight + input visible)
   * stays decoupled from in-flight text content. Cleared when the user picks
   * an option, skips, or commits the typed value to a real answer.
   */
  clarifyOtherSelected: Record<string, boolean>;
  /** True once the user clicks "Submit & continue" on the clarify composer. */
  clarifySubmitted: boolean;
}

export type Action =
  /** Live-update the active text question's draft input. */
  | { type: "draftText"; value: string }
  /** Live-update the profession Autocomplete draft. */
  | { type: "draftProfession"; value: string | null }
  /** User submitted an answer; advances `questionIndex`. */
  | { type: "answer"; field: string; value: string }
  /** Full personalization snapshot from REST (poll or initial fetch). */
  | { type: "serverSnapshot"; data: PersonalizationData }
  /** Partial patch from a WS stage event. */
  | {
      type: "serverPatch";
      patch: Partial<PersonalizationData>;
    }
  /**
   * Live status string emitted by a specific backend stage. Stored under
   * the stage that emitted it so the UI can scope display per step.
   */
  | { type: "progress"; stage: OnboardingStage; message: string }
  /** A backend stage finished — used to drive the processing checklist. */
  | { type: "stageComplete"; stage: OnboardingStage }
  /** User confirmed the writing-style reveal card. */
  | { type: "ackWriting" }
  /** User confirmed (or skipped) the todos reveal card. */
  | { type: "ackTodos" }
  /** User clicked "Understood" on the workflows reveal card. */
  | { type: "confirmWorkflows" }
  /** User finished the platform-connect popup flow. */
  | { type: "platformConnected"; platform: string }
  /** User skipped the platform-connect step without picking a platform. */
  | { type: "skipPlatforms" }
  /** User clicked Run on a todo; queues the message + flips the in-place
   *  chat stream on inside the `revealTodos` stage. Does NOT advance the
   *  stage — `ackTodoDemo` does that after the demo finishes. */
  | {
      type: "executeTodo";
      message: string;
      convoId: string;
      todo: {
        id: string;
        title: string;
        sourceEmail: { sender: string; subject: string } | null;
      };
    }
  /** Chat stage consumed the pending todo execution message. */
  | { type: "clearTodoExecutionMessage" }
  /** User clicked Continue after the in-place todo demo finished streaming;
   *  advances the cursor past `revealTodos` into `workflows`. */
  | { type: "ackTodoDemo" }
  /** Restart kicked off — flips state back to initial and locks UI. */
  | { type: "restartStart" }
  /** Server `/reset` settled (success or fail); unlocks UI. */
  | { type: "restartDone" }
  /** Hydrate from localStorage (or backend resume) on mount. */
  | { type: "hydrate"; partial: Partial<OnboardingState> }
  /** Hard reset to `initialState` (test/debug). */
  | { type: "reset" }
  /** Clarify-stage: questions returned from the backend (or mocked). */
  | { type: "clarifyLoaded"; questions: ClarifyQuestion[] }
  /** Clarify-stage: user picked a preset option for a question. */
  | { type: "clarifySelectOption"; questionId: string; value: string }
  /** Clarify-stage: user clicked the "Other" radio (no text typed yet). */
  | { type: "clarifyOtherSelect"; questionId: string }
  /** Clarify-stage: user is typing in the "Other" field. */
  | { type: "clarifyCustomDraft"; questionId: string; value: string }
  /** Clarify-stage: user committed the "Other" text as their answer. */
  | { type: "clarifyCustomCommit"; questionId: string }
  /** Clarify-stage: user marked the question skipped. */
  | { type: "clarifySkip"; questionId: string }
  /** Clarify-stage: switch active tab. */
  | { type: "clarifyTab"; questionId: string }
  /** Clarify-stage: user clicked Submit; advances cursor past clarify. */
  | { type: "clarifySubmit" };

export type StagePayload<K extends OnboardingStage> = StagePayloads[K];
