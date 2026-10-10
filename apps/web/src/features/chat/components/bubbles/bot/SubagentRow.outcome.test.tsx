// @vitest-environment jsdom

import type { ToolCallEntry } from "@shared/chat";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StepRow } from "@/features/chat/components/bubbles/bot/SubagentRow";

const call = (overrides: Partial<ToolCallEntry> = {}): ToolCallEntry => ({
  tool_name: "GOOGLECALENDAR_CUSTOM_DELETE_EVENT",
  tool_category: "calendar",
  message: "Delete calendar event",
  tool_call_id: "call-1",
  ...overrides,
});

const noop = (): undefined => undefined;

describe("StepRow approval outcome", () => {
  it("shows the receipt text next to the outcome chip", () => {
    render(
      <StepRow
        call={call()}
        isLast
        getIconUrl={noop}
        getIntegrationName={noop}
        pendingApprovalToolCallIds={new Set()}
        approvalOutcomeByToolCallId={
          new Map([
            ["call-1", { status: "approved", feedback: "Done: deleted xyz" }],
          ])
        }
      />,
    );
    expect(screen.getByText("Approved")).toBeDefined();
    expect(screen.getByText("Done: deleted xyz")).toBeDefined();
  });

  it("shows the chip alone when there is no feedback", () => {
    render(
      <StepRow
        call={call()}
        isLast
        getIconUrl={noop}
        getIntegrationName={noop}
        pendingApprovalToolCallIds={new Set()}
        approvalOutcomeByToolCallId={
          new Map([["call-1", { status: "denied", feedback: null }]])
        }
      />,
    );
    expect(screen.getByText("Denied")).toBeDefined();
  });

  it.each([
    ["executed", "Executed"],
    ["failed", "Failed"],
    ["unknown", "Unknown"],
  ] as const)("collapses a %s outcome to the small chip", (status, label) => {
    render(
      <StepRow
        call={call()}
        isLast
        getIconUrl={noop}
        getIntegrationName={noop}
        pendingApprovalToolCallIds={new Set()}
        approvalOutcomeByToolCallId={
          new Map([["call-1", { status, feedback: null }]])
        }
      />,
    );
    expect(screen.getByText(label)).toBeDefined();
  });
});
