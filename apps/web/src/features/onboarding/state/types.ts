import type { OnboardingNeed } from "../constants";
/**
 * Onboarding state shape and the discriminated union of actions the reducer
 * accepts. The reducer is the single mutation point; every effect/component
 * dispatches into it. Keep this file authoritative for what the flow
 * remembers and how it can change.
 */

export type Stage =
  | "questions"
  | "payment"
  | "paidReveal"
  | "platformPick"
  | "chat";

export interface OnboardingState {
  /** Answers keyed by `FIELD_NAMES`. Q2 lives in `selectedNeeds`, not here. */
  responses: Record<string, string>;
  questionIndex: number;
  draftProfession: string | null;
  selectedNeeds: OnboardingNeed[];
  /** Q2 "Something else", in the user's words. Empty when not used. */
  otherNeed: string;
  /** Whether Q2's "Something else" field is open. Owned here, not by the
   * chip row: the open field counts against the pick cap even before it
   * carries words, and the cap is the reducer's to enforce. */
  otherNeedOpen: boolean;
  /**
   * Whether Q1 + Q2 have reached the server (`PATCH /onboarding/preferences`).
   * The link-code mint composes its opener from those two fields server-side,
   * so nothing may mint until this is true.
   */
  preferencesPersisted: boolean;

  paidRevealAcked: boolean;
  platformsConfirmed: boolean;
  connectedPlatform: string | null;

  isRestarting: boolean;

  /** Whether this user has already watched the intro. Persisted like the rest
   * of the wizard's progress, so it never replays on reload. `null` until the
   * client has read storage — server and first client render agree on null. */
  introSeen: boolean | null;

  /** Which user's cache the reducer holds; `null` until the first load.
   * Derived nowhere else, so the persistence hook needs no state of its own. */
  hydratedFor: string | null;
}

export type Action =
  | { type: "draftProfession"; value: string | null }
  | { type: "answer"; field: string; value: string }
  | { type: "toggleNeed"; value: OnboardingNeed }
  | { type: "setOtherNeed"; value: string }
  | { type: "toggleOtherNeed" }
  | { type: "submitNeeds" }
  | { type: "preferencesPersisted" }
  | { type: "ackPaidReveal" }
  | { type: "platformConnected"; platform: string }
  | { type: "skipPlatforms" }
  | { type: "introSeen" }
  | { type: "restartStart" }
  | { type: "restartDone" }
  | { type: "hydrate"; partial: Partial<OnboardingState> }
  | { type: "hydrated"; userId: string }
  | { type: "reset" };
