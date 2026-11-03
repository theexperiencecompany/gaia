import type { OnboardingNeed } from "@shared/api/generated";

export type DemoKind = "inbox" | "meeting" | "followup" | "report";

interface NeedCopy {
  /** A line in the offer letter's duties, written to the person hiring. */
  duty: string;
  /** What GAIA commits to by day seven. Specific enough to be checked. */
  promise: string;
  demo: DemoKind;
}

export const NEED_COPY: Record<OnboardingNeed, NeedCopy> = {
  inbox: {
    duty: "Sort your inbox every morning and draft the replies",
    promise: "Your inbox sorted before you're up, every morning",
    demo: "inbox",
  },
  calendar: {
    duty: "Brief you before every meeting: who, why, what changed",
    promise: "A brief in your pocket 10 minutes before each meeting",
    demo: "meeting",
  },
  mornings: {
    duty: "Have your day laid out before you open your laptop",
    promise: "One morning text with everything that matters today",
    demo: "inbox",
  },
  reminders: {
    duty: "Remember the things you promised people, and nudge you",
    promise: "Nothing you said yes to slips through the week",
    demo: "followup",
  },
  grunt_work: {
    duty: "Take the weekly busywork you do on autopilot",
    promise: "One recurring chore of yours running without you",
    demo: "report",
  },
  tools: {
    duty: "Be the one place you ask, across every app you use",
    promise: "Your apps answering through one chat by day three",
    demo: "report",
  },
  founder_team_updates: {
    duty: "Chase the team's updates so you don't have to",
    promise: "Friday's team update drafted before you ask",
    demo: "report",
  },
  founder_competitors: {
    duty: "Watch your competitors and tell you what moved",
    promise: "A weekly note on what your competitors shipped",
    demo: "report",
  },
  executive_reports: {
    duty: "Read the reports and tell you the three lines that matter",
    promise: "Every report you get, cut to three lines",
    demo: "report",
  },
  executive_decisions: {
    duty: "Keep the decisions waiting on you in one short list",
    promise: "A daily list of decisions waiting on you, with context",
    demo: "followup",
  },
  sales_leads: {
    duty: "Follow up with every lead before they go cold",
    promise: "No lead goes three days without a follow-up",
    demo: "followup",
  },
  sales_call_research: {
    duty: "Research every prospect before you get on the call",
    promise: "A one-page brief before every sales call",
    demo: "meeting",
  },
  product_feedback: {
    duty: "Collect feedback from every channel into one place",
    promise: "This week's feedback in one doc, grouped by theme",
    demo: "report",
  },
  product_specs: {
    duty: "Turn your notes and threads into a first-draft spec",
    promise: "A first-draft spec from your notes, in a day",
    demo: "report",
  },
  marketing_content: {
    duty: "Keep the content calendar moving with first drafts",
    promise: "Next week's posts drafted by Friday",
    demo: "report",
  },
  marketing_reports: {
    duty: "Pull the numbers and write the weekly report",
    promise: "Your weekly marketing report, written for you",
    demo: "report",
  },
  engineering_prs: {
    duty: "Keep track of the PRs waiting on your review",
    promise: "A daily list of PRs waiting on you, oldest first",
    demo: "followup",
  },
  engineering_notifications: {
    duty: "Read the notifications so only the real ones reach you",
    promise: "Notifications cut to the ones that need you",
    demo: "inbox",
  },
  finance_numbers: {
    duty: "Chase people for numbers until they send them",
    promise: "Every number you're waiting on, chased daily",
    demo: "followup",
  },
  finance_reports: {
    duty: "Build the same weekly report, so you don't",
    promise: "This week's report built before you open the sheet",
    demo: "report",
  },
  creative_revisions: {
    duty: "Track every client revision and what's still open",
    promise: "Every open client revision in one list, updated daily",
    demo: "followup",
  },
  creative_deadlines: {
    duty: "Watch your deadlines and warn you early",
    promise: "A heads-up three days before every deadline",
    demo: "followup",
  },
  student_assignments: {
    duty: "Keep every assignment and due date in one plan",
    promise: "Every assignment you have, in one plan with dates",
    demo: "followup",
  },
  student_exams: {
    duty: "Build your revision plan and keep you on it",
    promise: "A revision plan for your next exam, with daily nudges",
    demo: "followup",
  },
};
