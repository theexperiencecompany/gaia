import { describe, expect, it } from "vitest";
import { APPROVAL_REQUEST_TOOL_NAME } from "../chat/approvals";
import type { StreamToolDataEntry } from "../chat/streaming";
import type { SubagentGroupData, ToolCallEntry } from "../chat/types";
import { SUBAGENT_GROUP_TOOL_NAME } from "../chat/types";
import { createOwnToolDataFold, foldOwnToolData } from "./streamFold";

const call = (id: string): ToolCallEntry => ({
  tool_name: "create_flowchart",
  tool_category: "creative",
  message: "Creating a flowchart",
  tool_call_id: id,
});

const group = (
  calls: ToolCallEntry[],
  completedAt: string | null = null,
): StreamToolDataEntry => ({
  tool_name: SUBAGENT_GROUP_TOOL_NAME,
  tool_category: "subagent",
  timestamp: "2026-09-23T10:00:00.000Z",
  data: {
    subagent_id: "row-1",
    subagent_name: "draw the flowchart",
    agent_type: "spawned",
    tool_calls: calls,
    duration_ms: null,
    token_count: null,
    started_at: "2026-09-23T10:00:00.000Z",
    completed_at: completedAt,
    icon_url: null,
    tool_category: "spawn_subagent",
    nested_subagents: [],
  } satisfies SubagentGroupData,
});

const card = (status: string): StreamToolDataEntry => ({
  tool_name: APPROVAL_REQUEST_TOOL_NAME,
  tool_category: "hil",
  data: { approval_id: "appr-1", gated_tool_name: "create_flowchart", status },
});

const executorCard: StreamToolDataEntry = {
  tool_name: "tool_calls_data",
  tool_category: "spawn_subagent",
  data: { tool_name: "spawn_subagent", tool_call_id: "tc_spawn" },
};

const groupOf = (entries: StreamToolDataEntry[]): SubagentGroupData => {
  const entry = entries.find((e) => e.tool_name === SUBAGENT_GROUP_TOOL_NAME);
  if (!entry) throw new Error("no subagent group in tool_data");
  return entry.data as SubagentGroupData;
};

const callsOf = (entries: StreamToolDataEntry[]): string[] =>
  groupOf(entries).tool_calls.map((c) => c.tool_call_id ?? "");

describe("foldOwnToolData", () => {
  it("adds the stream's own cards and keeps the ones another run wrote", () => {
    const { toolData } = foldOwnToolData(
      createOwnToolDataFold(),
      [executorCard],
      [group([call("a")]), card("pending")],
    );

    expect(toolData.map((e) => e.tool_name)).toEqual([
      "tool_calls_data",
      SUBAGENT_GROUP_TOOL_NAME,
      APPROVAL_REQUEST_TOOL_NAME,
    ]);
  });

  it("replaces its own entries on every flush instead of appending them again", () => {
    const first = foldOwnToolData(
      createOwnToolDataFold(),
      [executorCard],
      [group([call("a")])],
    );
    const second = foldOwnToolData(first.fold, first.toolData, [
      group([call("a"), call("b")]),
    ]);

    expect(second.toolData).toHaveLength(2);
    expect(callsOf(second.toolData)).toEqual(["a", "b"]);
  });

  it("joins a resumed run's calls onto the parked run's group, once across flushes", () => {
    const parked = [executorCard, group([call("before-pause")])];
    const first = foldOwnToolData(createOwnToolDataFold(), parked, [
      group([call("after")]),
    ]);
    const second = foldOwnToolData(first.fold, first.toolData, [
      group([call("after"), call("final")], "2026-09-23T10:05:00.000Z"),
    ]);

    expect(callsOf(second.toolData)).toEqual([
      "before-pause",
      "after",
      "final",
    ]);
    expect(groupOf(second.toolData).completed_at).toBe(
      "2026-09-23T10:05:00.000Z",
    );
  });

  it("settles a pending approval card in place rather than adding a second one", () => {
    const parked = [executorCard, card("pending")];
    const { toolData } = foldOwnToolData(createOwnToolDataFold(), parked, [
      card("approved"),
    ]);

    const cards = toolData.filter(
      (e) => e.tool_name === APPROVAL_REQUEST_TOOL_NAME,
    );
    expect(cards).toHaveLength(1);
    expect((cards[0].data as { status: string }).status).toBe("approved");
    expect(toolData.indexOf(cards[0])).toBe(1);
  });

  it("keeps another run's todo progress when it adds its own", () => {
    const existing: StreamToolDataEntry = {
      tool_name: "todo_progress",
      data: { executor: { source: "executor" } },
    };
    const own: StreamToolDataEntry = {
      tool_name: "todo_progress",
      data: { spawned_subagent: { source: "spawned_subagent" } },
    };

    const { toolData } = foldOwnToolData(
      createOwnToolDataFold(),
      [existing],
      [own],
    );

    expect(toolData).toHaveLength(1);
    expect(Object.keys(toolData[0].data as object).sort()).toEqual([
      "executor",
      "spawned_subagent",
    ]);
  });
});
