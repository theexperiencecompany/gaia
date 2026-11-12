import { describe, expect, it } from "vitest";
import { parseConversationEvent } from "./frames";

const AT = "2026-11-12T10:00:00+00:00";

const wire = (frame: unknown, streamId: string | null = null) =>
  JSON.stringify({ stream_id: streamId, frame });

const parse = (value: unknown) => parseConversationEvent(wire(value));

const frameOf = (value: unknown) => {
  const result = parse(value);
  if (!result.ok) {
    throw new Error(`expected a frame, got ${JSON.stringify(result.error)}`);
  }
  return result.event.frame;
};

const settled = (outcome: string, answers: string[]) => ({
  kind: "reply_settled",
  id: "rs",
  reply_id: "r",
  outcome,
  answers,
  through: 1,
  quote_target: null,
});

describe("parseConversationEvent", () => {
  it("parses a flat entry frame with a user message and fills the model's defaults", () => {
    const frame = frameOf({
      kind: "entry",
      seq: 3,
      at: AT,
      entry: { kind: "user_message", id: "m1", text: "hi", surface: "web" },
    });
    expect(frame).toEqual({
      kind: "entry",
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
        reaction: null,
        revision: 0,
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
        revision: 2,
      },
      settled("answered", ["m1"]),
    ];
    for (const entry of entries) {
      const result = parse({ kind: "entry", seq: 2, at: AT, entry });
      expect(result.ok, entry.kind).toBe(true);
    }
  });

  it("parses a reaction filled in place on a user message", () => {
    const frame = frameOf({
      kind: "entry_updated",
      seq: 1,
      entry: {
        kind: "user_message",
        id: "m1",
        text: "thanks",
        surface: "web",
        reaction: { emoji: "👍", by: "jev" },
        revision: 1,
      },
    });
    expect(frame.kind === "entry_updated" && frame.entry).toMatchObject({
      reaction: { emoji: "👍", by: "jev" },
      revision: 1,
    });
  });

  it("parses retract and state frames", () => {
    expect(frameOf({ kind: "retract", attempt_id: "a1" })).toEqual({
      kind: "retract",
      attempt_id: "a1",
    });
    const state = {
      kind: "state",
      head: 4,
      display: "awaiting_approval",
      work: [{ task_id: "k1", awaiting_approval: true }],
    };
    expect(frameOf(state)).toEqual(state);
  });

  it.each([
    ["response", { response: "Hel" }, { type: "response", chunk: "Hel" }],
    [
      "reasoning",
      { reasoning: { content: "hmm", subagent_id: null } },
      { type: "reasoning", content: "hmm", subagent_id: undefined },
    ],
    [
      "tool_output",
      { tool_output: { tool_call_id: "c1", output: "42", subagent_id: null } },
      {
        type: "tool_output",
        output: { tool_call_id: "c1", output: "42", subagent_id: undefined },
      },
    ],
    [
      "message_boundary",
      { message_boundary: { message_id: "msg", discarded: true } },
      { type: "message_boundary", messageId: "msg", discarded: true },
    ],
    [
      "subagent_start",
      {
        subagent_start: {
          subagent_id: "sa",
          subagent_name: "Gmail",
          agent_type: "spawned",
          started_at: AT,
          icon_url: null,
          tool_category: "gmail",
          parent_subagent_id: null,
        },
      },
      {
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
      },
    ],
    [
      "subagent_end",
      {
        subagent_end: { subagent_id: "sa", duration_ms: 12, token_count: null },
      },
      {
        type: "subagent_end",
        payload: { subagent_id: "sa", duration_ms: 12, token_count: null },
      },
    ],
    [
      "follow_up_actions",
      { follow_up_actions: ["Again"] },
      { type: "follow_up_actions", actions: ["Again"] },
    ],
    [
      "todo_progress",
      { todo_progress: { t1: { title: "x" } } },
      { type: "todo_progress", snapshot: { t1: { title: "x" } } },
    ],
  ])(
    "maps a tagged %s payload onto the stream event the accumulator folds",
    (type, body, event) => {
      const frame = frameOf({
        kind: "reply_delta",
        attempt_id: "a1",
        reply_id: null,
        index: 0,
        payload: { type, ...body },
      });
      expect(frame).toEqual({
        kind: "reply_delta",
        attempt_id: "a1",
        reply_id: null,
        index: 0,
        payload: event,
      });
    },
  );

  it("parses a work delta carrying a tool card", () => {
    const card = {
      tool_name: "tool_calls_data",
      tool_category: "gmail",
      data: { tool_name: "send", message: "Sending email" },
      timestamp: AT,
    };
    const frame = frameOf({
      kind: "work_delta",
      task_id: "k1",
      index: 3,
      payload: { type: "tool_data", tool_data: card },
    });
    expect(frame).toEqual({
      kind: "work_delta",
      task_id: "k1",
      index: 3,
      payload: { type: "tool_data", entry: card },
    });
  });

  it.each([
    ["not JSON", "{oops", "invalid_json"],
    ["an unknown frame kind", wire({ kind: "nope" }), "invalid_frame"],
    [
      "a payload with an unknown tag",
      wire({
        kind: "work_delta",
        task_id: "k",
        index: 0,
        payload: { type: "emoji_ack", emoji_ack: {} },
      }),
      "invalid_frame",
    ],
    [
      "an untagged payload",
      wire({
        kind: "work_delta",
        task_id: "k",
        index: 0,
        payload: { response: "x" },
      }),
      "invalid_frame",
    ],
    [
      "a negative delta index",
      wire({
        kind: "reply_delta",
        attempt_id: "a",
        reply_id: "r",
        index: -1,
        payload: { type: "response", response: "x" },
      }),
      "invalid_frame",
    ],
    [
      "an entry with seq 0",
      wire({
        kind: "entry",
        seq: 0,
        at: AT,
        entry: { kind: "notice", id: "n", text: "", origin: "x" },
      }),
      "invalid_frame",
    ],
    [
      "a settled reply missing its quote target",
      wire({
        kind: "entry",
        seq: 2,
        at: AT,
        entry: { ...settled("answered", ["m1"]), quote_target: undefined },
      }),
      "invalid_frame",
    ],
    [
      "an answered reply that answers nothing",
      wire({
        kind: "entry",
        seq: 2,
        at: AT,
        entry: settled("answered", []),
      }),
      "invalid_frame",
    ],
  ])("returns a typed error for %s instead of throwing", (_, raw, kind) => {
    const result = parseConversationEvent(raw);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.error.kind).toBe(kind);
    expect(!result.ok && result.error.raw).toBe(raw);
  });

  it("carries the stream id a reader resumes after", () => {
    const result = parseConversationEvent(
      wire({ kind: "retract", attempt_id: "a" }, "1731400000000-0"),
    );
    expect(result.ok && result.event.streamId).toBe("1731400000000-0");
  });

  it("refuses a bare frame without its event envelope", () => {
    const result = parseConversationEvent(
      JSON.stringify({ kind: "retract", attempt_id: "a" }),
    );
    expect(!result.ok && result.error.kind).toBe("invalid_frame");
  });

  it("lets a stopped reply settle with no answers", () => {
    expect(
      parse({ kind: "entry", seq: 2, at: AT, entry: settled("stopped", []) })
        .ok,
    ).toBe(true);
  });
});
