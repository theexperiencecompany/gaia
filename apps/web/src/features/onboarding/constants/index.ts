import type { OnboardingNeed } from "@shared/api/generated";

export type { OnboardingNeed } from "@shared/api/generated";

import type { Question } from "../types";
import {
  needOptions,
  OTHER_NEED,
  professionOptions,
  roleNeedOptions,
} from "./options";
import type { TypedNeedOption } from "./options.types";

export { needOptions, OTHER_NEED, professionOptions } from "./options";

/** A Q2 need id; the API's enum, so a chip the API rejects cannot be typed. */

/** How the role reads inside "Personalised for you, since you're …". */
export const ROLE_PHRASES: Record<string, string> = {
  founder: "a founder",
  executive: "an executive",
  sales: "in sales",
  product: "in product",
  creative: "a creative",
  engineering: "an engineer",
  marketing: "in marketing",
  finance: "in finance",
  student: "a student",
};

const allNeedOptions: readonly TypedNeedOption[] = [
  ...needOptions,
  ...Object.values(roleNeedOptions).flat(),
];

function isRole(
  profession: string,
): profession is keyof typeof roleNeedOptions {
  return profession in roleNeedOptions;
}

/** The Q2 grid for a Q1 answer: the role's two pains first, then the shared six. */
export function needOptionsFor(
  profession: string | null,
): readonly TypedNeedOption[] {
  const role =
    profession && isRole(profession) ? roleNeedOptions[profession] : undefined;
  return role ? [...role, ...needOptions] : needOptions;
}

export function isRoleNeed(value: string): boolean {
  return (
    !needOptions.some((option) => option.value === value) && isKnownNeed(value)
  );
}

export function isKnownNeed(value: string): value is OnboardingNeed {
  return allNeedOptions.some((option) => option.value === value);
}

export function needLabel(value: string): string | undefined {
  return allNeedOptions.find((option) => option.value === value)?.label;
}

/** Under the Q2 grid: how many picks are left, then, once they are spent,
 * that the picks set up the first thing and are not a ceiling. */
export function needsHint(picksLeft: number): string {
  if (picksLeft > 0) return `${picksLeft} left`;
  return "Don't worry, you can hand me more later.";
}

/** The catch-all chip; picking it opens a free-text field whose value replaces
 * this marker as the draft. Anything not in `professionOptions` is a typed job. */
export const OTHER_PROFESSION = "other";

export function isListedProfession(value: string): boolean {
  return (
    value !== OTHER_PROFESSION &&
    professionOptions.some((option) => option.value === value)
  );
}

export const OTHER_NEED_OPTION: TypedNeedOption = {
  value: OTHER_NEED,
  label: "Something else",
};

export const NEEDS_MIN_SELECTION = 1;
/** Mirrors `NEEDS_MAX_SELECTION` in apps/api user_models.py: the API 422s a
 * third need. "Something else" counts as a pick, so the field closes the grid. */
export const NEEDS_MAX_SELECTION = 3;

/** Mirror `OnboardingPreferences` in apps/api user_models.py: the profession
 * validator caps at 80 and `OTHER_NEED_MAX_LENGTH` at 120; longer text 422s.
 * 80, not 50, because Q1 asks "What do you do?" and people answer in a
 * sentence — "I'm a founder and designer building a startup" is already 46. */
export const PROFESSION_MAX_LENGTH = 80;
export const OTHER_NEED_MAX_LENGTH = 120;

/** Query key Dodo's return URL carries back into the wizard after checkout.
 * Mirrors ONBOARDING_CHECKOUT_RETURN_PATH in apps/api payment_models.py. */
export const CHECKOUT_RETURNED_PARAM = "checkout";

export const FIELD_NAMES = {
  PROFESSION: "profession",
  NEEDS: "needs",
} as const;

/** "Founder, got it." for a listed job; a typed or skipped one gets a plain ack. */
function professionAck(responses: Record<string, string>): string {
  const picked = responses[FIELD_NAMES.PROFESSION];
  const listed = picked && isListedProfession(picked);
  const label = listed
    ? professionOptions.find((option) => option.value === picked)?.label
    : undefined;
  return label ? `${label.split(" / ")[0]}, got it.` : "Got it.";
}

export const questions: Question[] = [
  {
    id: "1",
    lines: (_responses, { firstName }) => [
      firstName
        ? `Hey ${firstName}! I'm GAIA. Nice to meet you.`
        : "Hey! I'm GAIA. Nice to meet you.",
      "Think about everything you did yesterday. Email, calendar, meetings, sure, that's the obvious stuff.",
      "But also the research, the chasing people, the spreadsheet, the booking, that one thing you do every week and hate. I do all of that. Not you.",
      "So, what do you do for work?",
    ],
    fieldName: FIELD_NAMES.PROFESSION,
  },
  {
    id: "2",
    lines: (responses) => [
      professionAck(responses),
      "What do you want off your plate first? Pick up to three.",
    ],
    fieldName: FIELD_NAMES.NEEDS,
  },
];
