/**
 * sessionStorage persistence for the parts of `OnboardingState` that survive
 * a reload. Server-derived data (snapshot, completedStages, progressByStage)
 * is intentionally excluded — it's refetched from the backend on rehydrate
 * so we never serve a stale or contradictory snapshot.
 */

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
  connectedPlatform: string | null;
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
    connectedPlatform: state.connectedPlatform,
  };
}

/** Read the persisted slice from sessionStorage. Returns null on miss/parse-fail. */
export function loadPersisted(): Partial<OnboardingState> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
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
      connectedPlatform: parsed.connectedPlatform ?? null,
    };
  } catch {
    return null;
  }
}

/** Write the whitelisted slice to sessionStorage. Quota errors are swallowed. */
export function savePersisted(state: OnboardingState): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(pick(state)));
  } catch {
    // sessionStorage full or disabled — non-fatal
  }
}

/** Drop the persisted slice — called on restart so the user gets a clean slate. */
export function clearPersisted(): void {
  if (typeof window === "undefined") return;
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}
