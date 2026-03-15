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
  COMPANY_URL: "company_url",
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
      "Do you have a company or project website? I'll use it to understand what you're building so I can be more specific.",
    placeholder: "yourcompany.com",
    fieldName: FIELD_NAMES.COMPANY_URL,
    optional: true,
  },
  {
    id: "4",
    question:
      "Connect your Gmail. This is where I start working for you — I'll scan your inbox, draft replies in your voice, and turn action items into todos automatically.\n\nI never send anything without your approval. Your data stays private.",
    placeholder: "",
    fieldName: FIELD_NAMES.GMAIL,
  },
];
