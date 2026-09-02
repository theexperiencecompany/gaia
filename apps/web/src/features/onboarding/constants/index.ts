import type { NeedOption, ProfessionOption, Question } from "../types";

export const professionOptions: ProfessionOption[] = [
  { label: "Founder / CEO", value: "founder" },
  { label: "Executive", value: "executive" },
  { label: "Sales", value: "sales" },
  { label: "Product", value: "product" },
  { label: "Creative", value: "creative" },
  { label: "Engineering", value: "engineering" },
  { label: "Marketing", value: "marketing" },
  { label: "Finance", value: "finance" },
  { label: "Student", value: "student" },
  { label: "Other", value: "other" },
];

/**
 * Q2 options. `value` mirrors the backend `OnboardingNeed` StrEnum
 * (`apps/api/app/models/user_models.py`) one-for-one — the API rejects
 * anything outside that set, so the two lists must stay in lockstep.
 */
export const needOptions: NeedOption[] = [
  { value: "inbox", label: "Manage my inbox" },
  { value: "calendar", label: "Handle my calendar" },
  { value: "briefings", label: "Daily briefings" },
  { value: "todos", label: "Track my todos" },
  { value: "memory", label: "Remember everything" },
  { value: "research", label: "Do research" },
  { value: "automation", label: "Automate routines" },
  { value: "reach", label: "Reach me anywhere" },
];

export const NEEDS_MIN_SELECTION = 1;

export const FIELD_NAMES = {
  PROFESSION: "profession",
  NEEDS: "needs",
} as const;

export const questions: Question[] = [
  {
    id: "1",
    lines: [
      "Hey, I'm GAIA. I run your inbox, your calendar and the small stuff that piles up, so it stops landing on you.",
      "First, what do you do?",
    ],
    fieldName: FIELD_NAMES.PROFESSION,
  },
  {
    id: "2",
    lines: [
      "Noted.",
      "What do you want help with? Pick everything that applies.",
    ],
    fieldName: FIELD_NAMES.NEEDS,
  },
];
