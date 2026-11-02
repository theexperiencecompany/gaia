import type { OnboardingNeed } from "@shared/api/generated";

// ── Stage copy ────────────────────────────────────────────────────────────────

export function paymentIntroLines(firstName: string | undefined): string[] {
  return [
    firstName
      ? `So ${firstName}, quick thing before we go on. I'm not an app you're buying, I'm someone you're hiring.`
      : "Quick thing before we go on. I'm not an app you're buying, I'm someone you're hiring.",
    "A person doing all this costs a salary. I cost about a dollar a day.",
    "So, monthly or yearly?",
  ];
}

// ── Paywall value preview ─────────────────────────────────────────────────────

export const VALUE_PREVIEW_HEADING = "Your first week with me";
export const VALUE_PREVIEW_JOBS_HEADING = "We start with";
/** What the user typed into "Something else", quoted back as its own line. */
export const valuePreviewOtherNeedLine = (otherNeed: string): string =>
  `And the thing you mentioned: ${otherNeed}`;
/** True to the Terms (§5.1, §5.3): cancelling stops renewal, access runs to the period's end. No refund is promised. */
export const VALUE_PREVIEW_TRUST_LINE =
  "Cancel anytime in Settings. You keep everything until the period ends.";

/** What GAIA does in week one for each Q2 pick, in its own voice. */
export const NEED_WEEK_ONE: Record<OnboardingNeed, string> = {
  inbox: "Sort your inbox every morning and draft the replies for you to send",
  calendar: "Brief you before each meeting: who's coming and what's still open",
  mornings:
    "Have your morning brief ready: what's due, who's waiting, what's next",
  reminders: "Hold on to what you tell me and remind you before it slips",
  grunt_work: "Turn one weekly chore into a workflow that runs without you",
  tools: "Work across your connected apps so you stop switching between them",
  founder_team_updates: "Collect your team's updates so you stop chasing them",
  founder_competitors:
    "Keep an eye on your competitors and tell you what changed",
  executive_reports:
    "Read the reports you skip and hand you the lines that matter",
  executive_decisions:
    "Line up the decisions waiting on you, with context for each",
  sales_leads: "Flag leads going quiet and draft the follow-up",
  sales_call_research: "Research each prospect before your call",
  product_feedback: "Pull scattered feedback into one place",
  product_specs: "Draft specs from your notes",
  marketing_content: "Draft the content you're behind on",
  marketing_reports: "Put together the reports you build by hand",
  engineering_prs: "Keep track of the PRs waiting on you",
  engineering_notifications: "Cut your notifications down to what needs you",
  finance_numbers: "Draft the nudges to people you're waiting on numbers from",
  finance_reports: "Build the report you make every week",
  creative_revisions: "Track client revisions so none slip through",
  creative_deadlines: "Warn you before a deadline sneaks up",
  student_assignments: "Keep your assignments on track with due-date reminders",
  student_exams: "Build a study plan ahead of each exam",
};

export const FINISHING_MESSAGE = "One sec, starting our first chat…";
export const FINISH_FAILED_MESSAGE =
  "Hmm, I couldn't finish setting up our chat. Mind trying again?";
export const FINISH_CTA_LABEL = "Start chatting";
export const FINISH_RETRY_LABEL = "Try again";

/** The first words after the receipt. Static: no LLM call anywhere in onboarding. */
export const PLATFORM_INTRO_LINES = [
  "Last thing! Which app do you basically live in?",
  "That's where I'll be. Send me anything from anywhere, one text and it's handled. And if something needs you, I'll text you first.",
];
