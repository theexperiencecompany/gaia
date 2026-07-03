// ISO completion timestamp per step key, or null if the step is not yet complete.
export interface FirstStepsResponse {
  steps: Record<string, string | null>;
}
