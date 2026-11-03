import type { PaywallSubject } from "../labData";
import { type DemoKind, NEED_COPY } from "../needCopy";

interface DemoStep {
  label: string;
  detail: string;
}

export interface DemoScript {
  title: string;
  steps: DemoStep[];
  /** The thing the run produced, shown once every step is done. */
  artifactLabel: string;
  artifact: string;
  /** What GAIA says after the run, before the price. */
  closer: string;
}

const SAMPLE_SCRIPTS: Record<DemoKind, DemoScript> = {
  inbox: {
    title: "Sorting a sample inbox",
    steps: [
      {
        label: "Read 38 new emails",
        detail: "Newsletters and receipts set aside",
      },
      {
        label: "Found 3 that need you",
        detail: "A contract, a reschedule, an intro",
      },
      { label: "Drafted 3 replies", detail: "Saved as drafts, nothing sent" },
    ],
    artifactLabel: "Draft to Priya Shah",
    artifact:
      "Thursday at 3 works. I'll send the revised terms by Wednesday night so you have a day with them.",
    closer: "On your real inbox, I do this every morning before you're up.",
  },
  meeting: {
    title: "Prepping a sample 2pm call",
    steps: [
      {
        label: "Read the last 6 emails with Northwind",
        detail: "Plus the deck they sent",
      },
      {
        label: "Checked what changed since",
        detail: "New VP of ops, budget moved to Q1",
      },
      {
        label: "Wrote the brief",
        detail: "Three lines and one question to ask",
      },
    ],
    artifactLabel: "Brief: Northwind, 2pm",
    artifact:
      "They're deciding in Q1 now, not Q4. Their new VP of ops, Lena, will join. Ask what happens to the pilot if budget slips again.",
    closer: "For your real calendar, every meeting gets one of these.",
  },
  followup: {
    title: "Checking sample loose ends",
    steps: [
      { label: "Scanned last week's threads", detail: "Email and chat" },
      { label: "Found 4 things you said yes to", detail: "2 are due tomorrow" },
      { label: "Drafted the nudges", detail: "Waiting for your ok" },
    ],
    artifactLabel: "Due tomorrow",
    artifact:
      "You told Sam you'd send the pricing sheet. You told Ana you'd confirm Friday. Both drafts are ready.",
    closer: "With your real accounts, nothing you promise slips.",
  },
  report: {
    title: "Building a sample weekly update",
    steps: [
      { label: "Read the week in 3 channels", detail: "214 messages" },
      { label: "Pulled what shipped", detail: "9 items closed, 2 slipped" },
      {
        label: "Drafted the update",
        detail: "In the format you used last week",
      },
    ],
    artifactLabel: "Weekly update draft",
    artifact:
      "Shipped: billing export, faster search. Slipped: onboarding emails, now next Tuesday. One decision needed: the Q1 hire.",
    closer: "With your real tools, this lands every Friday without you asking.",
  },
};

/** The run GAIA shows: the first drafted starting job when there is one, else a sample for the top need. */
export function demoScriptFor(subject: PaywallSubject): DemoScript {
  const [job] = subject.startingJobs;
  if (job) {
    return {
      title: job.title,
      steps: job.steps.map((step) => ({
        label: step.title,
        detail: step.description,
      })),
      artifactLabel: "Ready to run",
      artifact: job.description,
      closer: "That's the job I drafted for you. Say go and it runs for real.",
    };
  }
  const [topNeed] = subject.needs;
  return SAMPLE_SCRIPTS[topNeed ? NEED_COPY[topNeed].demo : "inbox"];
}
