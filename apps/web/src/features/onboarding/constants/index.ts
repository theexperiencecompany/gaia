import type { ProfessionOption, Question } from "../types";

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
} as const;

export const questions: Question[] = [
  {
    id: "1",
    question:
      "Hi there! I'm GAIA, your personal AI assistant. What should I call you?",
    placeholder: "Enter your name...",
    fieldName: FIELD_NAMES.NAME,
  },
  {
    id: "2",
    question:
      "What's your profession or main area of focus? Knowing your profession or field helps me better manage your calendar, emails, and tasks. For example, I'll treat meetings and priorities differently for a student, a founder, or a designer.",
    placeholder: "e.g., Software Developer, Student, Designer...",
    fieldName: FIELD_NAMES.PROFESSION,
  },
];
