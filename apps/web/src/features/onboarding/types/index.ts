export interface Message {
  id: string;
  type: "bot" | "user";
  content: string;
  questionFieldName?: string;
}

export interface Question {
  id: string;
  /** GAIA's side of the turn, one bubble per line. */
  lines: string[];
  fieldName: string;
}

export interface ProfessionOption {
  label: string;
  value: string;
}

/** One Q2 option. `value` must match a backend `OnboardingNeed` member. */
export interface NeedOption {
  value: string;
  label: string;
}
