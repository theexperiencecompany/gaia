// @vitest-environment jsdom

import type { ToolCallEntry } from "@shared/chat";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StepRow } from "@/features/chat/components/bubbles/bot/SubagentRow";

vi.mock("@icons", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  PackageOpenIcon: () => <svg data-testid="integration-fallback-icon" />,
  ToolsIcon: () => <svg data-testid="tool-fallback-icon" />,
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
    expect(screen.queryByTestId("tool-fallback-icon")).toBeNull();
  });

  it("keeps the generic tool icon for a tool that belongs to no integration", () => {
    renderRow(call({ tool_category: "mystery" }));
    expect(screen.getByTestId("tool-fallback-icon")).toBeDefined();
    expect(screen.queryByTestId("integration-fallback-icon")).toBeNull();
  });
});
