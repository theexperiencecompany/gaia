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
  selectedNeeds: string[];
  /** Q2 "Something else", in the user's words. Empty when not used. */
  otherNeed: string;
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
}

export type Action =
  | { type: "draftProfession"; value: string | null }
  | { type: "answer"; field: string; value: string }
  | { type: "toggleNeed"; value: string }
  | { type: "setOtherNeed"; value: string }
  | { type: "submitNeeds" }
  | { type: "preferencesPersisted" }
  | { type: "ackPaidReveal" }
  | { type: "platformConnected"; platform: string }
  | { type: "skipPlatforms" }
  | { type: "restartStart" }
  | { type: "restartDone" }
  | { type: "hydrate"; partial: Partial<OnboardingState> }
  | { type: "reset" };
