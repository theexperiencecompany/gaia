// @vitest-environment jsdom

import type { ToolCallEntry } from "@shared/chat";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StepRow } from "@/features/chat/components/bubbles/bot/SubagentRow";

vi.mock("@icons", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  PackageOpenIcon: () => <svg data-testid="integration-fallback-icon" />,
}));

const call = (overrides: Partial<ToolCallEntry> = {}): ToolCallEntry => ({
  tool_name: "get_forecast",
  tool_category: "int_weather",
  message: "Get forecast",
  tool_call_id: "call-1",
  ...overrides,
});

const renderRow = (entry: ToolCallEntry) =>
  render(
    <StepRow
      call={entry}
      isLast
      pendingApprovalToolCallIds={new Set()}
      approvalOutcomeByToolCallId={new Map()}
    />,
  );

describe("ToolCallRow icon fallback", () => {
  it("shows the generic integration icon for an integration's tool with no logo", () => {
    renderRow(call({ integration_name: "Bundle Weather" }));
    expect(screen.getByTestId("integration-fallback-icon")).toBeDefined();
  });
});

const TRUNCATED_NOTE =
  "Showing the first part only. The full text is 4,455,615 characters long.";

describe("ToolCallRow output the server cut", () => {
  it("says under the expanded output how long the whole output was", () => {
    renderRow(call({ output: "sunny", output_original_length: 4_455_615 }));
    expect(screen.queryByText(TRUNCATED_NOTE)).toBeNull();

    fireEvent.click(screen.getByText("Get forecast"));

    expect(screen.getByText("sunny")).toBeDefined();
    expect(screen.getByText(TRUNCATED_NOTE)).toBeDefined();
  });

  it("says an old card's output is no longer stored when the server kept none of it", () => {
    renderRow(call({ output: "", output_original_length: 1_250 }));

    fireEvent.click(screen.getByText("Get forecast"));

    expect(screen.getByText("Output")).toBeDefined();
    expect(
      screen.getByText(
        "This text is no longer stored. It was 1,250 characters long.",
      ),
    ).toBeDefined();
  });

  it("says nothing under an output the server kept whole", () => {
    renderRow(call({ output: "sunny" }));

    fireEvent.click(screen.getByText("Get forecast"));

    expect(screen.getByText("sunny")).toBeDefined();
    expect(screen.queryByText(/characters long/)).toBeNull();
  });
});
