export type OnboardingStep =
  | "welcome"
  | "connect_integration"
  | "create_workflow"
  | "enable_notifications"
  | "complete";

export interface OnboardingStatus {
  completed: boolean;
  currentStep: OnboardingStep;
  completedSteps: OnboardingStep[];
}
