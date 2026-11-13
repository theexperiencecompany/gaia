import type { FirstStepKey } from "@shared/api/generated";

export type { FirstStepKey, FirstStepsResponse } from "@shared/api/generated";

/** One activation step; `done` is derived server-side and never set by the UI. */
export interface FirstStepStatus {
  key: FirstStepKey;
  done: boolean;
}

export type FirstStepsSurface = "dashboard" | "widget";
