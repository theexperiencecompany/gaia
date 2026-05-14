import type { OnboardingState } from "./types";

export const initialState: OnboardingState = {
  responses: {},
  questionIndex: 0,
  draftText: "",
  draftProfession: null,

  server: null,

  progressByStage: {},
  completedStages: new Set(),

  ackedWritingStyle: false,
  ackedTodos: false,

  workflowsConfirmed: false,
  platformsConfirmed: false,
  connectedPlatform: null,

  todoExecutionMessage: null,
  todoExecutionStarted: false,
  todoExecutionTodo: null,

  isRestarting: false,
};
