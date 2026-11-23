/** A screen of the mobile onboarding tour; local UI state, not a server phase. */
export type TourStep =
  | "welcome"
  | "connect_integration"
  | "create_workflow"
  | "enable_notifications"
  | "complete";
