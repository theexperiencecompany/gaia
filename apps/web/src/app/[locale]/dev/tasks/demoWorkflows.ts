import type { Workflow } from "@/features/workflows/api/workflowApi";

/** The steps GAIA worked out for each repeating task (workflow.steps). Illustrative values only. */

type Step = Workflow["steps"][number];

const step = (
  id: string,
  title: string,
  category: string,
  description: string,
): Step => ({
  id,
  title,
  category,
  description,
});

export const DEMO_STEPS: Record<string, Step[]> = {
  "github-triage": [
    step(
      "g1",
      "Read the pull request",
      "github",
      "Open the PR and read its description and diff.",
    ),
    step(
      "g2",
      "Find the Linear issue",
      "linear",
      "Match the PR to its Linear issue by branch or title.",
    ),
    step(
      "g3",
      "Add it to today's plan",
      "todos",
      "Write a two-line summary into today's plan.",
    ),
  ],
  "morning-brief": [
    step(
      "b1",
      "Read today's calendar",
      "googlecalendar",
      "List today's meetings with times and attendees.",
    ),
    step(
      "b2",
      "Find urgent emails",
      "gmail",
      "Look for anything urgent from the last 12 hours.",
    ),
    step(
      "b3",
      "Check the weather",
      "weather",
      "Get today's forecast for where you are.",
    ),
    step(
      "b4",
      "Send the brief",
      "notifications",
      "Send a brief that takes under a minute to read.",
    ),
  ],
  invoices: [
    step(
      "s1",
      "Check for an invoice",
      "gmail",
      "Confirm the email has an invoice attached.",
    ),
    step(
      "s2",
      "Save the PDF",
      "googledrive",
      "Save it to Finance/Invoices/<year> in Drive.",
    ),
    step("s3", "Name it", "googledrive", "Rename it by vendor and date."),
  ],
};
