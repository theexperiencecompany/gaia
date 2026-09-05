export interface FirstStepsResponse {
  // ISO completion timestamp per step key, or null if the step is not yet complete.
  steps: Record<string, string | null>;
  // Step keys the user has hidden server-side (persist across browsers).
  hidden_steps: string[];
  // Whether a GAIA proposal has ever existed; gates the "first approve" row.
  has_had_proposal: boolean;
  // Whether the user dismissed the whole widget for good.
  dismissed: boolean;
}
