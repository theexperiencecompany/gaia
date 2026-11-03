import type { OnboardingNeed } from "@shared/api/generated";

interface NeedCopy {
  /** The job, the way a sharp assistant would say it back to you. */
  job: string;
  /** When it happens, so the job reads as scheduled work, not an aspiration. */
  cadence: string;
  /** What the job costs a person doing it by hand, per week. An estimate, shown as one. */
  minutesPerWeek: number;
}

export const NEED_COPY: Record<OnboardingNeed, NeedCopy> = {
  inbox: {
    job: "I clear your inbox before you're up and leave drafts for the ones that need you",
    cadence: "Weekdays, 7am",
    minutesPerWeek: 150,
  },
  calendar: {
    job: "Every meeting gets a five-line brief: who, why, what changed, what to ask",
    cadence: "10 minutes before each",
    minutesPerWeek: 90,
  },
  mornings: {
    job: "One text at 8am with today's meetings, deadlines and the three things that matter",
    cadence: "Every morning",
    minutesPerWeek: 70,
  },
  reminders: {
    job: "I keep the list of everything you said yes to and nudge you before it slips",
    cadence: "As it comes up",
    minutesPerWeek: 45,
  },
  grunt_work: {
    job: "Tell me the chore you do every week on autopilot. It's mine from now on",
    cadence: "Weekly",
    minutesPerWeek: 120,
  },
  tools: {
    job: "Ask me instead of opening five apps. I'll go look and come back with the answer",
    cadence: "Whenever you ask",
    minutesPerWeek: 60,
  },
  founder_team_updates: {
    job: "I collect what everyone shipped and draft Friday's update for you to send",
    cadence: "Fridays",
    minutesPerWeek: 90,
  },
  founder_competitors: {
    job: "I watch your competitors' sites, launches and hires, and tell you what moved",
    cadence: "Mondays",
    minutesPerWeek: 60,
  },
  executive_reports: {
    job: "I read every report that lands and send you the three lines that matter",
    cadence: "As they arrive",
    minutesPerWeek: 120,
  },
  executive_decisions: {
    job: "Every decision waiting on you, in one list, with the context to make it",
    cadence: "Daily, 9am",
    minutesPerWeek: 60,
  },
  sales_leads: {
    job: "No lead goes three days without a follow-up. I draft it, you hit send",
    cadence: "Daily",
    minutesPerWeek: 150,
  },
  sales_call_research: {
    job: "A one-page brief on every prospect before the call: company, person, angle",
    cadence: "Before each call",
    minutesPerWeek: 120,
  },
  product_feedback: {
    job: "I pull feedback from support, Slack and calls into one doc, grouped by theme",
    cadence: "Fridays",
    minutesPerWeek: 90,
  },
  product_specs: {
    job: "Give me your notes and the thread. You get a first-draft spec the same day",
    cadence: "On request",
    minutesPerWeek: 120,
  },
  marketing_content: {
    job: "Next week's posts drafted in your voice by Friday, for you to cut",
    cadence: "Fridays",
    minutesPerWeek: 150,
  },
  marketing_reports: {
    job: "I pull the numbers and write the weekly report you've been doing by hand",
    cadence: "Mondays",
    minutesPerWeek: 90,
  },
  engineering_prs: {
    job: "A morning list of PRs waiting on you, oldest first, with what each one changes",
    cadence: "Weekdays, 9am",
    minutesPerWeek: 60,
  },
  engineering_notifications: {
    job: "I read the notifications so only the ones that need you reach you",
    cadence: "All day",
    minutesPerWeek: 90,
  },
  finance_numbers: {
    job: "I chase people for the numbers you need, politely, daily, until they send them",
    cadence: "Daily",
    minutesPerWeek: 90,
  },
  finance_reports: {
    job: "The same weekly report, built before you open the sheet",
    cadence: "Mondays",
    minutesPerWeek: 120,
  },
  creative_revisions: {
    job: "Every open client revision in one list, updated as the emails come in",
    cadence: "As they arrive",
    minutesPerWeek: 60,
  },
  creative_deadlines: {
    job: "A heads-up three days before every deadline, with what's still missing",
    cadence: "As they near",
    minutesPerWeek: 45,
  },
  student_assignments: {
    job: "Every assignment and due date in one plan, and a nudge before each one",
    cadence: "Sundays, plus nudges",
    minutesPerWeek: 60,
  },
  student_exams: {
    job: "A revision plan for your next exam, broken into days, and I keep you on it",
    cadence: "Daily",
    minutesPerWeek: 90,
  },
};
