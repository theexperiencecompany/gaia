import type { Schema } from "@shared/api/generated";
export type FirstStepKey = Schema<"FirstStepKey">;

/** One activation step; `done` is derived server-side and never set by the UI. */
export interface FirstStepStatus {
  key: FirstStepKey;
  done: boolean;
}

export type FirstStepsResponse = Schema<"FirstStepsResponse">;

export type FirstStepsSurface = "dashboard" | "widget";
