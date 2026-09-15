import { isKnownNeed } from "../constants";
import type { OnboardingState } from "./types";

// v3 = the paid-first flow. A bumped key is what stops a half-finished v2
// run (clarify answers, reveal acks) from rehydrating into a state shape
// that no longer has those stages. The user id is part of the key: the cache
// is one account's progress, and a second account on the same browser must
// start from question one rather than inherit it.
const STORAGE_KEY_PREFIX = "gaia-onboarding-state-v3";

const storageKey = (userId: string) => `${STORAGE_KEY_PREFIX}:${userId}`;

// The intro is remembered per user under its own key: it survives the wizard
// blob's version bumps (an intro already watched should not replay because
// the state shape changed) and is written at a different moment.
const INTRO_SEEN_PREFIX = "gaia.onboarding.introSeen";

const introSeenKey = (userId: string) =>
  userId ? `${INTRO_SEEN_PREFIX}.${userId}` : null;

interface PersistedShape {
  responses: Record<string, string>;
  questionIndex: number;
  selectedNeeds: string[];
  otherNeed: string;
  preferencesPersisted: boolean;
  paidRevealAcked: boolean;
  platformsConfirmed: boolean;
  connectedPlatform: string | null;
}

function pick(state: OnboardingState): PersistedShape {
  return {
    responses: state.responses,
    questionIndex: state.questionIndex,
    selectedNeeds: state.selectedNeeds,
    otherNeed: state.otherNeed,
    preferencesPersisted: state.preferencesPersisted,
    paidRevealAcked: state.paidRevealAcked,
    platformsConfirmed: state.platformsConfirmed,
    connectedPlatform: state.connectedPlatform,
  };
}

export function loadPersisted(userId: string): Partial<OnboardingState> | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem(storageKey(userId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<PersistedShape>;
    return {
      responses: parsed.responses ?? {},
      questionIndex: parsed.questionIndex ?? 0,
      // A chip set from an older build must not resurrect a value the API
      // no longer accepts.
      selectedNeeds: (parsed.selectedNeeds ?? []).filter(isKnownNeed),
      otherNeed: parsed.otherNeed ?? "",
      // The open flag is derived, not stored: words in the cache mean the
      // field was open when they were typed.
      otherNeedOpen: (parsed.otherNeed ?? "") !== "",
      preferencesPersisted: parsed.preferencesPersisted ?? false,
      paidRevealAcked: parsed.paidRevealAcked ?? false,
      platformsConfirmed:
        parsed.platformsConfirmed ?? !!parsed.connectedPlatform,
      connectedPlatform: parsed.connectedPlatform ?? null,
    };
  } catch {
    return null;
  }
}

export function savePersisted(userId: string, state: OnboardingState): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.setItem(storageKey(userId), JSON.stringify(pick(state)));
  } catch {
    // localStorage unavailable (private mode, quota, etc.) — persistence is best-effort.
  }
}

export function clearPersisted(userId: string): void {
  if (typeof window === "undefined") return;
  try {
    localStorage.removeItem(storageKey(userId));
  } catch {
    // localStorage unavailable (private mode, quota, etc.) — persistence is best-effort.
  }
}

export function loadIntroSeen(userId: string): boolean {
  if (typeof window === "undefined") return false;
  const key = introSeenKey(userId);
  if (!key) return false;
  try {
    return localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

export function saveIntroSeen(userId: string): void {
  if (typeof window === "undefined") return;
  const key = introSeenKey(userId);
  if (!key) return;
  try {
    localStorage.setItem(key, "1");
  } catch {
    // localStorage unavailable (private mode, quota, etc.) — best-effort.
  }
}

export function clearIntroSeen(userId: string): void {
  if (typeof window === "undefined") return;
  const key = introSeenKey(userId);
  if (!key) return;
  try {
    localStorage.removeItem(key);
  } catch {
    // localStorage unavailable (private mode, quota, etc.) — best-effort.
  }
}
