import type { ComponentType } from "react";
import { Homework } from "./concepts/Homework";
import { LiveInbox } from "./concepts/LiveInbox";
import { TomorrowBriefed } from "./concepts/TomorrowBriefed";
import { WeekBack } from "./concepts/WeekBack";
import type { PaywallConceptProps } from "./labData";

export type ConceptId = "inbox" | "calendar" | "week" | "homework";

export interface PaywallConcept {
  id: ConceptId;
  name: string;
  Component: ComponentType<PaywallConceptProps>;
  /** What in the frame is a stand-in for a pipeline the lab does not call. */
  mocked: string;
  bet: string;
  lift: string;
  risk: string;
  buildCost: string;
  needs: string;
}

/** Per-user costs below are from prod llm_calls, last 90 days, cost / distinct users per lane. */
export const PAYWALL_CONCEPTS: PaywallConcept[] = [
  {
    id: "inbox",
    name: "Your inbox, live",
    Component: LiveInbox,
    mocked: "Gmail connect, the 100-email read and the drafts",
    bet: "Nothing sells an assistant like watching it clear your own inbox. Connect Gmail before the price, GAIA triages it live, and the price is framed as keeping that every morning.",
    lift: "It's the only concept where the proof is their own data. Today the 76% who never open checkout have seen zero work. Seeing their own investor email flagged with a reply already drafted is the moment people screenshot.",
    risk: "Adds a Google OAuth screen before the price, and some people will drop there instead. A thin or empty inbox reads as a dud. Promising 'read-only' means a new read-only Gmail config, and Google's restricted-scope review applies.",
    buildCost:
      "About a week. The triage pipeline already exists. New work: allow one Gmail connect before payment, a read-only auth config, a reply-drafting step, and moving connect ahead of the paywall. Cost per trial user is about $0.03: triage $0.0017, writing style $0.0086, todos $0.0024, social and card $0.002, plus 3 drafts at about $0.005 each. At 140 paywall viewers a month that's about $4 a month.",
    needs:
      "Gmail OAuth before payment. Today POST /api/v1/integrations/connect/{id} is not on the entitlement allowlist, so unpaid users get a 402, and the Gmail config asks for gmail.modify, not read-only. Existing pieces: process_onboarding_intelligence runs on Gmail connect and writes onboarding.triage_summary (100 emails scanned, important_emails with a reason each). 88 users have one, 50 from the last 90 days. No step drafts replies yet.",
  },
  {
    id: "calendar",
    name: "Tomorrow, briefed",
    Component: TomorrowBriefed,
    mocked: "Calendar connect, the meeting read and every brief",
    bet: "A briefing for tomorrow is the most concrete 'it already did something' moment for anyone with meetings. Connect the calendar, GAIA briefs each meeting tomorrow, and flags the one that needs a decision first.",
    lift: "It's about tomorrow, which feels urgent in a way 'your inbox' doesn't, and the flagged meeting gives a reason to pay tonight. It also works for people who don't live in email.",
    risk: "An empty tomorrow (weekends, students, ICs) is an anticlimax. Briefs are only as good as the email and context behind them, and they're thin without Gmail. Calendar tools are flaky today: GOOGLECALENDAR_CUSTOM_GET_EVENT fails 58% of the time, plus 'Future attached to a different loop' errors.",
    buildCost:
      "One to two weeks. There's no onboarding calendar pipeline yet; the calendar:meeting_prep system workflow exists but runs per event after payment. Needs the same pre-pay connect allowance, a batch brief job, and the calendar tool fixes first. About $0.03 to $0.04 per trial user (googlecalendar_agent is about $0.004 a call, times 2 calls per meeting).",
    needs:
      "Google Calendar OAuth before payment (same 402 today). The config already includes calendar.readonly, but it also asks for calendar.events. A Gmail read makes the briefs much better.",
  },
  {
    id: "week",
    name: "Your week back",
    Component: WeekBack,
    mocked: "Nothing live. Job wording and time estimates are drafted copy",
    bet: "No permissions, no wait. Turn their two answers into a ledger of specific jobs GAIA takes from today, each with when it happens and the time it gives back, so $30 reads as about $1 an hour.",
    lift: "Removes the abstract 'dollar a day' and replaces it with their own week, in numbers. No OAuth means nothing to drop off on, and it costs nothing to show everyone, including the 53 mobile signups.",
    risk: "It's still a claim, not proof, so it can't produce a 'holy shit' moment. The time estimates are ours, and a skeptic will discount them. 'Something else' answers need an LLM line.",
    buildCost:
      "Two to three days: the copy table above, plus an LLM line for 'Something else' answers (about $0.002 per user at the onboarding_workflow_suggestions rate). It uses the existing checkout.",
    needs:
      "Nothing new. Profession and needs are already saved before the paywall. Starting jobs, when drafted, add an 'already drafted' line.",
  },
  {
    id: "homework",
    name: "I did my homework",
    Component: Homework,
    mocked: "The public-web research and every finding",
    bet: "GAIA researches them from public sources while they answer the two questions, then opens with what it found and what it would do about each thing. That's a good assistant's first day: they already know who you are.",
    lift: "It's the 'it already knows me' moment without any OAuth, so no permission screen to drop off on. Each finding comes with a concrete next action, so the value is specific to them, not generic.",
    risk: "Can feel creepy, and the wrong-person risk is real (common names, gmail.com addresses give little to go on). Email-only signups get a thin result. A single wrong fact kills trust instantly.",
    buildCost:
      "Three to five days. The social-profile step (onboarding_social_profile, about $0.0013 per user) and the holo-card bio (about $0.0008) run today, but only inside the Gmail pipeline. Run them at signup with web search, add a findings-to-actions call, and add a 'not me' path. About $0.01 per user.",
    needs:
      "Name and email, which we already have. Public web search. Runs under /api/v1/onboarding, which is already on the allowlist. Needs a privacy line in the terms.",
  },
];
