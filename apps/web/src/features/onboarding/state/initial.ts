import type { OnboardingState } from "./types";

export const initialState: OnboardingState = {
  responses: {},
  questionIndex: 0,
  draftText: "",
  draftProfession: null,

  server: null,

  progressMessage: null,
  completedStages: new Set(),

  ackedWritingStyle: false,
  ackedTodos: false,

  workflowsConfirmed: false,
  connectedPlatform: null,

  todoExecutionMessage: null,

  submissionError: false,
  isRestarting: false,
};
