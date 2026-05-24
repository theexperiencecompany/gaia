/**
 * Onboarding state shape and the discriminated union of actions the reducer
 * accepts. The reducer is the single mutation point; every effect/component
 * dispatches into it. Keep this file authoritative for what the flow
 * remembers and how it can change.
 */

import type { ClarifyAnswer, ClarifyQuestion } from "../types";
import type { OnboardingStage, PersonalizationData } from "../types/websocket";

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
  responses: Record<string, string>;
  questionIndex: number;
  draftText: string;
  draftProfession: string | null;

  server: PersonalizationData | null;

  progressByStage: Partial<Record<OnboardingStage, string>>;
  completedStages: Set<OnboardingStage>;

  ackedWritingStyle: boolean;
  ackedTodos: boolean;

  workflowsConfirmed: boolean;
  platformsConfirmed: boolean;
  connectedPlatform: string | null;

  todoExecutionMessage: string | null;
  todoExecutionConvoId: string | null;
  todoExecutionStarted: boolean;
  todoExecutionTodo: {
    id: string;
    title: string;
    sourceEmail: { sender: string; subject: string } | null;
  } | null;

  isRestarting: boolean;

  clarifyQuestions: ClarifyQuestion[] | null;
  clarifyAnswers: Record<string, ClarifyAnswer>;
  clarifyActiveTab: string | null;
  clarifyCustomDrafts: Record<string, string>;
  clarifyOtherSelected: Record<string, boolean>;
  clarifySubmitted: boolean;
}

export type Action =
  | { type: "draftText"; value: string }
  | { type: "draftProfession"; value: string | null }
  | { type: "answer"; field: string; value: string }
  | { type: "serverSnapshot"; data: PersonalizationData }
  | {
      type: "serverPatch";
      patch: Partial<PersonalizationData>;
    }
  | { type: "progress"; stage: OnboardingStage; message: string }
  | { type: "stageComplete"; stage: OnboardingStage }
  | { type: "ackWriting" }
  | { type: "ackTodos" }
  | { type: "confirmWorkflows" }
  | { type: "platformConnected"; platform: string }
  | { type: "skipPlatforms" }
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
  | { type: "clearTodoExecutionMessage" }
  | { type: "ackTodoDemo" }
  | { type: "restartStart" }
  | { type: "restartDone" }
  | { type: "hydrate"; partial: Partial<OnboardingState> }
  | { type: "reset" }
  | { type: "clarifyLoaded"; questions: ClarifyQuestion[] }
  | { type: "clarifySelectOption"; questionId: string; value: string }
  | { type: "clarifyOtherSelect"; questionId: string }
  | { type: "clarifyCustomDraft"; questionId: string; value: string }
  | { type: "clarifyCustomCommit"; questionId: string }
  | { type: "clarifySkip"; questionId: string }
  | { type: "clarifyTab"; questionId: string }
  | { type: "clarifySubmit" };
