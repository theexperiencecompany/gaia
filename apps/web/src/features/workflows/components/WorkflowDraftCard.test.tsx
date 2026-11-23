// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WorkflowDraftData } from "@/types/features/toolDataTypes";
import WorkflowDraftCard from "./WorkflowDraftCard";

vi.mock("./WorkflowModal", () => ({ default: () => null }));

afterEach(cleanup);

function renderDraft(cron: string) {
  const draft: WorkflowDraftData = {
    suggested_title: "Standup digest",
    suggested_description: "Summarise standup notes",
    prompt: "Summarise standup notes",
    trigger_type: "schedule",
    cron_expression: cron,
  };
  render(<WorkflowDraftCard draft={draft} />);
}

describe("WorkflowDraftCard schedule label", () => {
  it("describes a step schedule in words, the same as the schedule builder", () => {
    renderDraft("*/15 * * * *");
    expect(screen.getByText("Every 15 minutes")).toBeTruthy();
    expect(screen.queryByText(/Custom:/)).toBeNull();
  });

  it("names the 21st of the month with the right ordinal", () => {
    renderDraft("0 9 21 * *");
    expect(screen.queryByText(/21th/)).toBeNull();
    expect(screen.getByText(/day 21 of the month/)).toBeTruthy();
  });
});
