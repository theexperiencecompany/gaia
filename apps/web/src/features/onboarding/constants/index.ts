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
  {
    value: "inbox",
    label: "Manage my inbox",
    sub: "Triage, label, draft replies",
  },
  {
    value: "calendar",
    label: "Handle my calendar",
    sub: "Schedule and prep meetings",
  },
  {
    value: "briefings",
    label: "Daily briefings",
    sub: "Morning summary of what matters",
  },
  { value: "todos", label: "Track my todos", sub: "Capture tasks, remind me" },
  {
    value: "memory",
    label: "Remember everything",
    sub: "People, context, notes",
  },
  { value: "research", label: "Do research", sub: "Search, read, summarize" },
  {
    value: "automation",
    label: "Automate routines",
    sub: "Workflows that run without me",
  },
  {
    value: "reach",
    label: "Reach me anywhere",
    sub: "WhatsApp, Telegram, voice",
  },
];

export const NEEDS_MIN_SELECTION = 1;

export const FIELD_NAMES = {
  PROFESSION: "profession",
  NEEDS: "needs",
} as const;

export const questions: Question[] = [
  {
    id: "1",
    question: "What do you do?",
    fieldName: FIELD_NAMES.PROFESSION,
  },
  {
    id: "2",
    question: "How can GAIA help?",
    fieldName: FIELD_NAMES.NEEDS,
  },
];
