/**
 * Regression test for the browser task rendering twice in the tool thread.
 *
 * The bug: `browser_task` opens its own "Browser" subagent group (the agent's
 * actions stream into it), but the executor's `browser_task` tool call was also
 * emitted as a root-level row. The thread showed two adjacent, near-identical
 * entries — "Task / Browser" immediately followed by "Browser / Subagent" —
 * which reads as a duplicate because it describes the same work twice.
 *
 * The fix consumes the call into its group, exactly as a handoff/spawn call is
 * consumed: the task and result move onto the group and only the group renders.
 */

import type { SubagentGroupData, ToolCallEntry } from "@shared/chat";
import { describe, expect, it } from "vitest";
import { buildBackendTimeline } from "@/features/chat/components/bubbles/bot/TextBubble/useSubagentSynthesis";

const browserCall: ToolCallEntry = {
  tool_name: "browser_task",
  tool_category: "browser",
  message: "Task",
  tool_call_id: "call_abc",
  inputs: { task: "Open example.com", start_url: "https://example.com" },
  output: "BROWSER TASK COMPLETED.",
};

const browserGroup: SubagentGroupData = {
  subagent_id: "browser:sess1",
  subagent_name: "Browser",
  agent_type: "spawned",
  tool_calls: [
    {
      tool_name: "done",
      tool_category: "browser",
      message: "Wrapping up",
      tool_call_id: "browser:sess1:3:0",
      inputs: { text: "Example Domain" },
    },
  ],
  duration_ms: 30_100,
  token_count: null,
  started_at: "2026-08-27T15:42:26.234677+00:00",
  completed_at: "2026-08-27T15:42:56.334677+00:00",
  icon_url: null,
  tool_category: "browser",
  nested_subagents: [],
};

describe("buildBackendTimeline — browser task", () => {
  it("renders the browser run once, as its group", () => {
    const timeline = buildBackendTimeline([browserCall], [browserGroup]);

    expect(timeline).toHaveLength(1);
    expect(timeline[0].kind).toBe("subagent");
  });

  it("moves the call's task and result onto the group", () => {
    const timeline = buildBackendTimeline(
      [browserCall],
      [structuredClone(browserGroup)],
    );

    const item = timeline[0];
    if (item.kind !== "subagent") throw new Error("expected a subagent item");
    expect(item.data.handoff_input).toBe("Open example.com");
    expect(item.data.handoff_output).toBe("BROWSER TASK COMPLETED.");
  });

  it("keeps the group's own actions", () => {
    const timeline = buildBackendTimeline(
      [browserCall],
      [structuredClone(browserGroup)],
    );

    const item = timeline[0];
    if (item.kind !== "subagent") throw new Error("expected a subagent item");
    expect(item.data.tool_calls.map((c) => c.tool_name)).toEqual(["done"]);
  });

  it("still renders the call when no group arrived", () => {
    // A dropped subagent_start (mid-turn stream attach) must not swallow the
    // run entirely — better one plain row than a silently missing one.
    const otherGroup: SubagentGroupData = {
      ...structuredClone(browserGroup),
      subagent_id: "gmail:1",
      subagent_name: "Gmail",
      agent_type: "handoff",
      tool_category: "gmail",
      tool_calls: [],
    };
    const timeline = buildBackendTimeline([browserCall], [otherGroup]);

    const browserRows = timeline.filter(
      (item) => item.kind === "tool" && item.data.tool_name === "browser_task",
    );
    expect(browserRows).toHaveLength(1);
  });

  it("does not consume a second browser call into the same group", () => {
    const secondCall: ToolCallEntry = {
      ...browserCall,
      tool_call_id: "call_def",
    };
    const timeline = buildBackendTimeline(
      [browserCall, secondCall],
      [structuredClone(browserGroup)],
    );

    // One group for the first call; the second has no group left to fold into,
    // so it stays visible rather than disappearing.
    expect(timeline.filter((i) => i.kind === "subagent")).toHaveLength(1);
    expect(timeline.filter((i) => i.kind === "tool")).toHaveLength(1);
  });
});
