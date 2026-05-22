import type { ClarifyAnswer, ClarifyQuestion } from "../types";
import type { OnboardingState } from "./types";

const STORAGE_KEY = "gaia-onboarding-state-v2";

interface PersistedShape {
  responses: Record<string, string>;
  questionIndex: number;
  draftText: string;
  draftProfession: string | null;
  ackedWritingStyle: boolean;
  ackedTodos: boolean;
  workflowsConfirmed: boolean;
  platformsConfirmed: boolean;
  connectedPlatform: string | null;
  clarifyQuestions: ClarifyQuestion[] | null;
  clarifyAnswers: Record<string, ClarifyAnswer>;
  clarifyActiveTab: string | null;
  clarifyCustomDrafts: Record<string, string>;
  clarifyOtherSelected: Record<string, boolean>;
  clarifySubmitted: boolean;
  // todoExecutionMessage is deliberately omitted — persisting it re-sends on reload.
  todoExecutionStarted: boolean;
  todoExecutionConvoId: string | null;
  todoExecutionTodo: {
    id: string;
    title: string;
    sourceEmail: { sender: string; subject: string } | null;
  } | null;
}

function pick(state: OnboardingState): PersistedShape {
  return {
    responses: state.responses,
    questionIndex: state.questionIndex,
    draftText: state.draftText,
    draftProfession: state.draftProfession,
    ackedWritingStyle: state.ackedWritingStyle,
    ackedTodos: state.ackedTodos,
    workflowsConfirmed: state.workflowsConfirmed,
    platformsConfirmed: state.platformsConfirmed,
    connectedPlatform: state.connectedPlatform,
    clarifyQuestions: state.clarifyQuestions,
    clarifyAnswers: state.clarifyAnswers,
    clarifyActiveTab: state.clarifyActiveTab,
    clarifyCustomDrafts: state.clarifyCustomDrafts,
    clarifyOtherSelected: state.clarifyOtherSelected,
    clarifySubmitted: state.clarifySubmitted,
    todoExecutionStarted: state.todoExecutionStarted,
    todoExecutionConvoId: state.todoExecutionConvoId,
    todoExecutionTodo: state.todoExecutionTodo,
  };
}

export function loadPersisted(): Partial<OnboardingState> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedShape>;
    return {
      responses: parsed.responses ?? {},
      questionIndex: parsed.questionIndex ?? 0,
      draftText: parsed.draftText ?? "",
      draftProfession: parsed.draftProfession ?? null,
      ackedWritingStyle: parsed.ackedWritingStyle ?? false,
      ackedTodos: parsed.ackedTodos ?? false,
      workflowsConfirmed: parsed.workflowsConfirmed ?? false,
      platformsConfirmed:
        parsed.platformsConfirmed ?? !!parsed.connectedPlatform,
      connectedPlatform: parsed.connectedPlatform ?? null,
      clarifyQuestions: parsed.clarifyQuestions ?? null,
      clarifyAnswers: parsed.clarifyAnswers ?? {},
      clarifyActiveTab: parsed.clarifyActiveTab ?? null,
      clarifyCustomDrafts: parsed.clarifyCustomDrafts ?? {},
      clarifyOtherSelected: parsed.clarifyOtherSelected ?? {},
      clarifySubmitted: parsed.clarifySubmitted ?? false,
      todoExecutionStarted: parsed.todoExecutionStarted ?? false,
      todoExecutionConvoId: parsed.todoExecutionConvoId ?? null,
      todoExecutionTodo: parsed.todoExecutionTodo ?? null,
    };
  } catch {
    return null;
  }
}

export function savePersisted(state: OnboardingState): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pick(state)));
  } catch {}
}

export function clearPersisted(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {}
}
