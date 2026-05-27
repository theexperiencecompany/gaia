import type { ClarifyQuestion } from "../types";

export const CLARIFY_INTRO =
  "Quick. Three questions so the todos I draft for you actually move things forward.";

export const CLARIFY_PROCESSING_MSG =
  "Got it. Lining up the right todos based on that.";

export const CLARIFY_OTHER_LABEL = "Other";
export const CLARIFY_SKIP_LABEL = "Skip this question";
export const CLARIFY_SKIP_REPLY = "Skipped";

export const CLARIFY_MOCK_QUESTIONS: ClarifyQuestion[] = [
  {
    id: "scope",
    kind: "scope",
    question: "What needs to move forward this week?",
    options: [
      "The main project: shipping the next milestone",
      "External work: outreach, meetings, customers",
      "Internal work: planning, hiring, ops",
    ],
  },
  {
    id: "blocker",
    kind: "blocker",
    question: "Where are you actually stuck right now?",
    options: [
      "Too many open threads, nothing's closing",
      "Waiting on someone else to come back",
      "I know what to do, just not getting to it",
    ],
  },
  {
    id: "constraint",
    kind: "constraint",
    question: "How much focused time can you realistically carve out?",
    options: [
      "A few hours every day",
      "One or two deep-work blocks total",
      "Honestly, very little. I'm mostly in meetings",
    ],
  },
];
