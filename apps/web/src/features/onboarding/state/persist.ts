import type { OnboardingState } from "./types";

// v3 = the paid-first flow. A bumped key is what stops a half-finished v2
// run (clarify answers, reveal acks) from rehydrating into a state shape
// that no longer has those stages.
const STORAGE_KEY = "gaia-onboarding-state-v3";

interface PersistedShape {
  responses: Record<string, string>;
  questionIndex: number;
  selectedNeeds: string[];
  paidRevealAcked: boolean;
  greetingAcked: boolean;
  platformsConfirmed: boolean;
  connectedPlatform: string | null;
}

function pick(state: OnboardingState): PersistedShape {
  return {
    responses: state.responses,
    questionIndex: state.questionIndex,
    selectedNeeds: state.selectedNeeds,
    paidRevealAcked: state.paidRevealAcked,
    greetingAcked: state.greetingAcked,
    platformsConfirmed: state.platformsConfirmed,
    connectedPlatform: state.connectedPlatform,
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
      selectedNeeds: parsed.selectedNeeds ?? [],
      paidRevealAcked: parsed.paidRevealAcked ?? false,
      greetingAcked: parsed.greetingAcked ?? false,
      platformsConfirmed:
        parsed.platformsConfirmed ?? !!parsed.connectedPlatform,
      connectedPlatform: parsed.connectedPlatform ?? null,
    };
  } catch {
    return null;
  }
}

export function savePersisted(state: OnboardingState): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(pick(state)));
  } catch {
    // localStorage unavailable (private mode, quota, etc.) — persistence is best-effort.
  }
}

export function clearPersisted(): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // localStorage unavailable (private mode, quota, etc.) — persistence is best-effort.
  }
}
