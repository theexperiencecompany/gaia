import type { ProfessionOption, Question } from "../types";

/** Standard dimensions for the holo card across onboarding UI */
export const HOLO_CARD_HEIGHT = 470;
export const HOLO_CARD_WIDTH = 330;

export const professionOptions: ProfessionOption[] = [
  { label: "Student", value: "student" },
  { label: "Teacher", value: "teacher" },
  { label: "Engineer", value: "engineer" },
  { label: "Developer", value: "developer" },
  { label: "Designer", value: "designer" },
  { label: "Manager", value: "manager" },
  { label: "Consultant", value: "consultant" },
  { label: "Entrepreneur", value: "entrepreneur" },
  { label: "Researcher", value: "researcher" },
  { label: "Writer", value: "writer" },
  { label: "Artist", value: "artist" },
  { label: "Doctor", value: "doctor" },
  { label: "Lawyer", value: "lawyer" },
  { label: "Accountant", value: "accountant" },
  { label: "Sales", value: "sales" },
  { label: "Marketing", value: "marketing" },
  { label: "Analyst", value: "analyst" },
  { label: "Freelancer", value: "freelancer" },
  { label: "Retired", value: "retired" },
  { label: "Other", value: "other" },
];

export const FIELD_NAMES = {
  NAME: "name",
  PROFESSION: "profession",
  GMAIL: "gmail",
} as const;

export const questions: Question[] = [
  {
    id: "1",
    question:
      "Hi there. I'm GAIA, your personal AI assistant. What should I call you?",
    placeholder: "Enter your name...",
    fieldName: FIELD_NAMES.NAME,
  },
  {
    id: "2",
    question:
      "What's your profession or main area of focus? This helps me treat your calendar, emails, and tasks appropriately.",
    placeholder: "e.g., Software Developer, Student, Designer...",
    fieldName: FIELD_NAMES.PROFESSION,
  },
  {
    id: "3",
    question:
      "Last step — connect your Gmail and I'll scan your inbox, surface what matters, and set up your first action items.",
    placeholder: "",
    fieldName: FIELD_NAMES.GMAIL,
  },
];
