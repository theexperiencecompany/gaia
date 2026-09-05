export interface Message {
  id: string;
  type: "bot" | "user";
  content: string;
  questionFieldName?: string;
}

export interface Question {
  id: string;
  /** GAIA's side of the turn, one bubble per line, given the answers so far. */
  lines: (responses: Record<string, string>) => string[];
  fieldName: string;
}

export interface ProfessionOption {
  label: string;
  value: string;
}

/** One Q2 option. `value` must match a backend `OnboardingNeed` member, except
 * the `OTHER_NEED` catch-all, which is never sent as a need. */
export interface NeedOption {
  value: string;
  label: string;
}
