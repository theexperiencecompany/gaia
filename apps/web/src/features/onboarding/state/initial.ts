import type { OnboardingState } from "./types";

export const initialState: OnboardingState = {
  responses: {},
  questionIndex: 0,
  draftProfession: null,
  selectedNeeds: [],
  otherNeed: "",
  preferencesPersisted: false,

  paidRevealAcked: false,
  greetingAcked: false,
  platformsConfirmed: false,
  connectedPlatform: null,

  isRestarting: false,
};
