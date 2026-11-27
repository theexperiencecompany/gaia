// @vitest-environment jsdom

import type { ToolCallEntry } from "@shared/chat";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SubagentRow } from "@/features/chat/components/bubbles/bot/SubagentRow";
import type { EnrichedSubagentGroup } from "@/features/chat/components/bubbles/bot/UnifiedToolThread";

const REMOVED =
  /This text is no longer stored\. It was [\d,]+ characters long\./;

const cutCall = (id: string, length: number): ToolCallEntry => ({
  tool_name: "get_forecast",
  tool_category: "int_weather",
  message: `Get forecast ${id}`,
  tool_call_id: id,
  output: "",
  output_original_length: length,
});

const group: EnrichedSubagentGroup = {
  subagent_id: "sa-1",
  subagent_name: "Planner",
  agent_type: "handoff",
  started_at: "2026-10-01T09:00:00Z",
  tool_calls: [cutCall("tc-1", 900), cutCall("tc-2", 4_200)],
  duration_ms: 3_000,
  token_count: 120,
  completed_at: "2026-10-01T09:00:03Z",
  icon_url: null,
  tool_category: null,
  nested_subagents: [],
  handoff_input: "Plan the weekend",
  handoff_output: "",
  handoff_output_original_length: 2_000,
  step_keys: ["tc-1", "tc-2"],
};

describe("SubagentRow whose calls and result were all cut", () => {
  it("still lists every call, and each one and the result say they are no longer stored", () => {
    render(
      <SubagentRow
        group={group}
        isLast
        isStreaming={false}
        pendingApprovalToolCallIds={new Set()}
      />,
    );

    fireEvent.click(screen.getByText("Planner"));

    expect(screen.getByText("Result")).toBeDefined();
    expect(
      screen.getByText(
        "This text is no longer stored. It was 2,000 characters long.",
      ),
    ).toBeDefined();

    fireEvent.click(screen.getByText("Get forecast tc-1"));
    fireEvent.click(screen.getByText("Get forecast tc-2"));

    expect(screen.getAllByText(REMOVED)).toHaveLength(3);
  });
});
