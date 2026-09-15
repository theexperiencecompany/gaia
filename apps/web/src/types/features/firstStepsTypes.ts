export const FIRST_STEP_KEYS = [
  "say_hi",
  "connect_integration",
  "link_platform",
  "create_workflow",
] as const;

export type FirstStepKey = (typeof FIRST_STEP_KEYS)[number];

/** One activation step; `done` is derived server-side and never set by the UI. */
export interface FirstStepStatus {
  key: FirstStepKey;
  done: boolean;
}

export interface FirstStepsResponse {
  steps: FirstStepStatus[];
  /** Whether the user collapsed the checklist to its header. Persisted, so it
   * survives a reload and follows the user across devices. */
  collapsed: boolean;
}

export type FirstStepsSurface = "dashboard" | "widget";
