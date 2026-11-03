import type {
  OnboardingNeed,
  PersonalizationWorkflow,
  PlanDuration,
} from "@shared/api/generated";
import type { ProfessionValue } from "@/features/onboarding/constants/options.types";
import { ADVERTISED_PRO_MONTHLY } from "@/features/pricing/advertisedPrice";
import { LAB_MOCKS, type LabMock } from "./mockLive";

/** What the paywall knows about the person by the time it renders: the two
 * onboarding answers, their name, and the starting jobs when drafting finished. */
export interface PaywallSubject {
  firstName: string | undefined;
  profession: ProfessionValue;
  needs: OnboardingNeed[];
  startingJobs: PersonalizationWorkflow[];
}

export interface PaywallConceptProps {
  subject: PaywallSubject;
  /** What the live pipelines would have returned for this person. */
  mock: LabMock;
  onCheckout: (period: PlanDuration) => void;
}

export interface LabPersona {
  id: string;
  label: string;
  subject: PaywallSubject;
  mock: LabMock;
}

export const MONTHLY_PRICE_MINOR = ADVERTISED_PRO_MONTHLY.amount;
/** The live Dodo catalogue's yearly Pro price; the lab runs without the API. */
export const YEARLY_PRICE_MINOR = 30000;
export const PRICE_CURRENCY = ADVERTISED_PRO_MONTHLY.currency;

const FOUNDER_JOBS: PersonalizationWorkflow[] = [
  {
    id: "lab-job-inbox",
    title: "Morning inbox sweep",
    description:
      "Every weekday at 7am, sort overnight mail and draft replies to anything from investors or the team.",
    steps: [
      {
        id: "s1",
        category: "gmail",
        title: "Read 41 overnight emails",
        description: "Skip newsletters and receipts",
      },
      {
        id: "s2",
        category: "gmail",
        title: "Flag 3 that need you",
        description: "Two investors, one hire",
      },
      {
        id: "s3",
        category: "gmail",
        title: "Draft replies in your voice",
        description: "Saved as drafts, nothing sent",
      },
      {
        id: "s4",
        category: "general",
        title: "Text you the summary",
        description: "Before your first meeting",
      },
    ],
  },
  {
    id: "lab-job-updates",
    title: "Friday team update digest",
    description:
      "Collect what each lead shipped this week from Slack and Linear, and draft the update you send on Fridays.",
    steps: [
      {
        id: "s1",
        category: "slack",
        title: "Read the week in #eng and #sales",
        description: "",
      },
      {
        id: "s2",
        category: "linear",
        title: "Pull closed Linear issues",
        description: "",
      },
      {
        id: "s3",
        category: "general",
        title: "Draft the Friday update",
        description: "",
      },
    ],
  },
];

export const LAB_PERSONAS: LabPersona[] = [
  {
    id: "founder",
    label: "Maya, founder, 2 starting jobs",
    subject: {
      firstName: "Maya",
      profession: "founder",
      needs: ["inbox", "founder_team_updates", "calendar"],
      startingJobs: FOUNDER_JOBS,
    },
    mock: LAB_MOCKS.founder,
  },
  {
    id: "sales",
    label: "Dev, sales, no jobs yet",
    subject: {
      firstName: "Dev",
      profession: "sales",
      needs: ["sales_leads", "sales_call_research"],
      startingJobs: [],
    },
    mock: LAB_MOCKS.sales,
  },
  {
    id: "student",
    label: "No name, student",
    subject: {
      firstName: undefined,
      profession: "student",
      needs: ["student_assignments", "reminders"],
      startingJobs: [],
    },
    mock: LAB_MOCKS.student,
  },
];
