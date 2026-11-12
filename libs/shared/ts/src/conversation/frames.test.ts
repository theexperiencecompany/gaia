import { describe, expect, it } from "vitest";
import { parseConversationFrame } from "./frames";

const AT = "2026-11-12T10:00:00+00:00";

const parse = (value: unknown) => parseConversationFrame(JSON.stringify(value));

const frameOf = (value: unknown) => {
  const result = parse(value);
  if (!result.ok) throw new Error(`expected a frame, got ${result.error.kind}`);
  return result.frame;
};

describe("parseConversationFrame", () => {
  it("parses an entry frame with a user message and fills the model's defaults", () => {
    const frame = frameOf({
      kind: "entry",
      entry: {
        seq: 3,
        at: AT,
        entry: { kind: "user_message", id: "m1", text: "hi", surface: "web" },
      },
    });
    expect(frame).toEqual({
      kind: "entry",
      entry: {
        seq: 3,
        at: AT,
        entry: {
          kind: "user_message",
          id: "m1",
          text: "hi",
          surface: "web",
          platform_message_id: null,
          reply_to: null,
          retry_of: null,
          file_ids: [],
          voice: false,
        },
      },
    });
  });

  it("parses every entry kind the server can append", () => {
    const entries = [
      { kind: "stop_requested", id: "s", by: "user", covers_through: null },
      { kind: "barge_in", id: "b", reply_id: "r", heard_text: "he" },
      {
        kind: "workflow_fired",
        id: "w",
        workflow_id: "wf",
        execution_id: "ex",
        context: { a: 1 },
      },
      {
        kind: "todo_woke",
        id: "t",
        todo_id: "td",
        wake: { kind: "schedule", trigger_names: [], approval_summary: null },
      },
      { kind: "notice", id: "n", text: "hello", origin: "reminder" },
      {
        kind: "work_started",
        id: "ws",
        task_id: "k",
        cause_through: 1,
        answers: ["m1"],
      },
      { kind: "approval_requested", id: "ar", task_id: "k", approval_id: "ap" },
      {
        kind: "approval_decided",
        id: "ad",
        approval_id: "ap",
        decision: "approve",
      },
      {
        kind: "work_finished",
        id: "wf2",
        task_id: "k",
        outcome: "done",
        report: "ok",
      },
      {
        kind: "reply",
        id: "rp",
        reply_id: "r",
        attempt_id: "a",
        text: "",
        tool_data: [],
        follow_up_actions: [],
        heard_through: null,
      },
      {
        kind: "reply_settled",
        id: "rs",
        reply_id: "r",
        outcome: "answered",
        answers: ["m1"],
        through: 1,
      },
    ];
    for (const entry of entries) {
      const result = parse({ kind: "entry", entry: { seq: 2, at: AT, entry } });
      expect(result.ok, entry.kind).toBe(true);
    }
  });

  it("parses entry_updated, retract and state frames", () => {
    expect(frameOf({ kind: "retract", attempt_id: "a1" })).toEqual({
      kind: "retract",
      attempt_id: "a1",
    });
    expect(
      frameOf({
        kind: "state",
        head: 4,
        display: "working",
        work_phase: "running",
      }),
    ).toEqual({
      kind: "state",
      head: 4,
      display: "working",
      work_phase: "running",
    });
    const updated = frameOf({
      kind: "entry_updated",
      entry: {
        seq: 5,
        at: AT,
        entry: {
          kind: "reply",
          id: "rp",
          reply_id: "r",
          attempt_id: "a",
          text: "done",
        },
      },
    });
    expect(updated.kind).toBe("entry_updated");
  });

  it.each([
    ["text", { response: "Hel" }, { type: "response", chunk: "Hel" }],
    [
      "reasoning",
      { content: "hmm", subagent_id: null },
      { type: "reasoning", content: "hmm", subagent_id: undefined },
    ],
    [
      "tool output",
      { tool_call_id: "c1", output: "42", subagent_id: null },
      {
        type: "tool_output",
        output: { tool_call_id: "c1", output: "42", subagent_id: undefined },
      },
    ],
    [
      "message boundary",
      { message_id: "msg", discarded: true },
      { type: "message_boundary", messageId: "msg", discarded: true },
    ],
    [
      "subagent end",
      { subagent_id: "sa", duration_ms: 12, token_count: null },
      {
        type: "subagent_end",
        payload: { subagent_id: "sa", duration_ms: 12, token_count: null },
      },
    ],
    [
      "follow-up actions",
      { follow_up_actions: ["Again"] },
      { type: "follow_up_actions", actions: ["Again"] },
    ],
  ])(
    "turns a %s delta payload into the stream event the accumulator folds",
    (_, payload, event) => {
      const frame = frameOf({
        kind: "delta",
        attempt_id: "a1",
        reply_id: "r1",
        payload,
      });
      expect(frame).toEqual({
        kind: "delta",
        attempt_id: "a1",
        reply_id: "r1",
        task_id: null,
        payload: event,
      });
    },
  );

  it("turns a subagent start payload into a subagent_start event", () => {
    const frame = frameOf({
      kind: "delta",
      attempt_id: "a1",
      task_id: "k1",
      payload: {
        subagent_id: "sa",
        subagent_name: "Gmail",
        subagent: null,
        agent_type: "spawned",
        started_at: AT,
        icon_url: null,
        tool_category: "gmail",
        parent_subagent_id: null,
      },
    });
    expect(frame.kind === "delta" && frame.payload).toEqual({
      type: "subagent_start",
      payload: {
        subagent_id: "sa",
        subagent_name: "Gmail",
        agent_type: "spawned",
        started_at: AT,
        icon_url: undefined,
        tool_category: "gmail",
        parent_subagent_id: undefined,
      },
    });
  });

  it("turns a tool card payload into a tool_data event", () => {
    const card = {
      tool_name: "tool_calls_data",
      tool_category: "gmail",
      data: { tool_name: "send", message: "Sending email" },
      timestamp: AT,
      mcp_ui: null,
      mcp_server_url: null,
    };
    const frame = frameOf({
      kind: "delta",
      attempt_id: "a1",
      task_id: "k1",
      payload: card,
    });
    expect(frame.kind === "delta" && frame.payload).toEqual({
      type: "tool_data",
      entry: card,
    });
  });

  it.each([
    ["not JSON", "{oops", "invalid_json"],
    [
      "an unknown frame kind",
      JSON.stringify({ kind: "nope" }),
      "invalid_frame",
    ],
    [
      "a delta with both targets",
      JSON.stringify({
        kind: "delta",
        attempt_id: "a",
        reply_id: "r",
        task_id: "t",
        payload: { response: "x" },
      }),
      "invalid_frame",
    ],
    [
      "a delta with neither target",
      JSON.stringify({
        kind: "delta",
        attempt_id: "a",
        payload: { response: "x" },
      }),
      "invalid_frame",
    ],
    [
      "a delta with an unrecognised payload",
      JSON.stringify({
        kind: "delta",
        attempt_id: "a",
        reply_id: "r",
        payload: { nope: 1 },
      }),
      "invalid_frame",
    ],
    [
      "an entry with seq 0",
      JSON.stringify({
        kind: "entry",
        entry: {
          seq: 0,
          at: AT,
          entry: { kind: "notice", id: "n", text: "", origin: "x" },
        },
      }),
      "invalid_frame",
    ],
    [
      "an answered reply that answers nothing",
      JSON.stringify({
        kind: "entry",
        entry: {
          seq: 2,
          at: AT,
          entry: {
            kind: "reply_settled",
            id: "rs",
            reply_id: "r",
            outcome: "answered",
            answers: [],
            through: 1,
          },
        },
      }),
      "invalid_frame",
    ],
  ])("returns a typed error for %s instead of throwing", (_, raw, kind) => {
    const result = parseConversationFrame(raw);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error.kind).toBe(kind);
    expect(!result.ok && result.error.raw).toBe(raw);
  });

  it("lets a stopped reply settle with no answers", () => {
    const result = parse({
      kind: "entry",
      entry: {
        seq: 2,
        at: AT,
        entry: {
          kind: "reply_settled",
          id: "rs",
          reply_id: "r",
          outcome: "stopped",
          answers: [],
          through: 1,
        },
      },
    });
    expect(result.ok).toBe(true);
  });
});
