/** Use-case titles lead with the searched task and fit the snippet; descriptions say what runs, where and when. */
import { describe, expect, it } from "vitest";

import type { UseCase } from "@/types/features/workflowTypes";
import { generateUseCaseMetadata } from "@/utils/seoUtils";
import {
  generateUseCaseDescription,
  generateUseCaseTitle,
} from "@/utils/useCaseMeta";

/** One workflow step per tool category, as the explore API returns them. */
function stepsFor(categories: readonly string[]): UseCase["steps"] {
  return categories.map((category, index) => ({
    id: `step_${index}`,
    title: category,
    description: "",
    category,
  }));
}

/** Shapes of production explore workflows (/workflows/explore). */
function makeUseCase(overrides: Partial<UseCase> = {}): UseCase {
  const integrations = overrides.integrations ?? ["reminders"];
  return {
    title: "Rent Reminder",
    description:
      "A heads-up three days before month-end, so rent is never late.",
    action_type: "workflow",
    categories: ["featured"],
    published_id: "id",
    slug: "rent-reminder",
    trigger_config: { type: "schedule" },
    integrations,
    steps: stepsFor(integrations),
    ...overrides,
  };
}

const INBOX_TRIAGE = makeUseCase({
  title: "Inbox Triage",
  description:
    "Daily digest: triages the last day's emails and creates todos for action items.",
  integrations: ["gmail", "gaia", "todos"],
  slug: "inbox-triage",
});

const MEETING_BRIEFING = makeUseCase({
  title: "Meeting Briefing",
  description:
    "Researches attendees and prepares a briefing before each meeting.",
  integrations: ["googlecalendar", "gmail", "gaia"],
  trigger_config: { type: "integration" },
  slug: "meeting-briefing",
});

const LONG_TITLE = makeUseCase({
  title:
    "Weekly Cross-Team Engineering Retrospective and Planning Digest for Leads",
  integrations: ["github", "googlecalendar"],
});

/** The title as a result snippet shows it: the layout template appends " | GAIA" unless absolute. */
function renderedTitle(metadataTitle: unknown): string {
  if (typeof metadataTitle === "string") return `${metadataTitle} | GAIA`;
  return (metadataTitle as { absolute: string }).absolute;
}

describe("generateUseCaseTitle", () => {
  it("leads with 'AI <task>' and names the external apps, not GAIA's built-in steps", () => {
    expect(generateUseCaseTitle(makeUseCase())).toBe(
      "AI Rent Reminder: Automated Workflow",
    );
    expect(generateUseCaseTitle(INBOX_TRIAGE)).toBe(
      "AI Inbox Triage with Gmail",
    );
    expect(generateUseCaseTitle(MEETING_BRIEFING)).toBe(
      "AI Meeting Briefing with Google Calendar and Gmail",
    );
  });

  it("does not double an AI or Workflow already in the title", () => {
    const title = generateUseCaseTitle(
      makeUseCase({ title: "AI Morning Workflow", integrations: [] }),
    );
    expect(title).toBe("AI Morning Workflow");
  });

  it("renders within 60 characters including the brand suffix", () => {
    for (const input of [
      makeUseCase(),
      INBOX_TRIAGE,
      MEETING_BRIEFING,
      LONG_TITLE,
    ]) {
      const rendered = renderedTitle(generateUseCaseMetadata(input).title);
      expect(rendered.length, rendered).toBeLessThanOrEqual(60);
    }
    expect(renderedTitle(generateUseCaseMetadata(INBOX_TRIAGE).title)).toBe(
      "AI Inbox Triage with Gmail | GAIA",
    );
  });

  it("trims a title too long for the snippet at a word, without the suffix", () => {
    const rendered = renderedTitle(generateUseCaseMetadata(LONG_TITLE).title);
    expect(rendered.length).toBeLessThanOrEqual(60);
    expect(rendered).not.toContain("| GAIA");
    expect(`AI ${LONG_TITLE.title}`.startsWith(rendered)).toBe(true);
  });
});

describe("generateUseCaseDescription", () => {
  it("adds steps, apps and trigger to the short API summary to reach 120-160 chars", () => {
    expect(generateUseCaseDescription(makeUseCase())).toBe(
      "A heads-up three days before month-end, so rent is never late. A 1-step GAIA workflow using Reminders. Runs on a schedule. Add it to your GAIA from this page.",
    );
    for (const input of [makeUseCase(), INBOX_TRIAGE, MEETING_BRIEFING]) {
      const desc = generateUseCaseDescription(input);
      expect(desc.length, desc).toBeGreaterThanOrEqual(120);
      expect(desc.length, desc).toBeLessThanOrEqual(160);
    }
  });

  it("lists GAIA's apps without naming GAIA twice", () => {
    expect(generateUseCaseDescription(INBOX_TRIAGE)).toContain(
      "A 3-step GAIA workflow using Gmail and Todos.",
    );
  });

  it("trims a summary longer than the snippet at a word with an ellipsis", () => {
    const desc = generateUseCaseDescription(
      makeUseCase({ description: "word ".repeat(60) }),
    );
    expect(desc.length).toBeLessThanOrEqual(160);
    expect(desc.endsWith("word…")).toBe(true);
  });
});
