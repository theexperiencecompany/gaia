import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NEW_MESSAGE_BREAK_TOKEN } from "../utils/messageBreakUtils";
import discardedPreambleTurn from "./__fixtures__/discarded-preamble-turn.json";
import executorReasoning from "./__fixtures__/executor-reasoning.json";
import imageGeneration from "./__fixtures__/image-generation.json";
import plainTextTurn from "./__fixtures__/plain-text-turn.json";
import subagentTurn from "./__fixtures__/subagent-turn.json";
import todoProgress from "./__fixtures__/todo-progress.json";
import toolTurn from "./__fixtures__/tool-turn.json";
import { parseChatStreamEvent } from "./streaming";
import {
  applyStreamEvent,
  createTurnAccumulator,
  type TurnAccumulator,
} from "./turnAccumulator";
import type { SubagentGroupData, TodoProgressSnapshot } from "./types";

// Reducer branches that stamp wall-clock time (executor reasoning entries,
// subagent completed_at, todo_progress entry timestamps) go through
// new Date().toISOString(). Freeze it so the golden snapshots are exact.
const FIXED_NOW = "2026-06-15T12:00:00.000Z";

// Fold a golden transcript (raw SSE data-strings) the same way every transport
// does: parse each frame into events, then reduce them into one accumulator.
const fold = (frames: string[]): TurnAccumulator =>
  frames
    .flatMap((frame) => parseChatStreamEvent(frame))
    .reduce(applyStreamEvent, createTurnAccumulator());

const reasoningStep = (content: string) => ({
  tool_name: "reasoning",
  tool_category: "reasoning",
  message: "",
  reasoning: content,
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(FIXED_NOW));
});

afterEach(() => {
  vi.useRealTimers();
});

describe("turnAccumulator golden replay", () => {
  it("(a) plain text turn: concatenates response deltas, sets follow-ups", () => {
    const acc = fold(plainTextTurn);

    expect(acc).toEqual({
      responseText: "Hello, world",
      currentMessageStart: 0,
      messageBreakPending: false,
      toolData: [],
      followUpActions: ["Tell me more", "Summarize this"],
      imageData: null,
      generatingImage: false,
      todoProgress: null,
      extras: {},
    });
    // Invariant: init / main_response_complete / done are turn-session events
    // and never touch message state.
    expect(acc.toolData).toHaveLength(0);
  });

  it("(b) tool turn: tool_output merges onto the matching tool_call_id", () => {
    const acc = fold(toolTurn);

    expect(acc).toEqual({
      responseText: "Done.",
      currentMessageStart: 0,
      messageBreakPending: false,
      toolData: [
        {
          tool_name: "tool_calls_data",
          tool_category: "search",
          data: {
            tool_name: "web_search",
            tool_category: "search",
            message: "Searching the web",
            tool_call_id: "tc-1",
            inputs: { query: "weather today" },
            output: "Found 3 results",
          },
        },
        {
          tool_name: "tool_calls_data",
          tool_category: "email",
          data: {
            tool_name: "send_email",
            tool_category: "email",
            message: "Sending email",
            tool_call_id: "tc-2",
            inputs: { to: "a@b.com" },
            output: "Email sent",
          },
        },
      ],
      followUpActions: null,
      imageData: null,
      generatingImage: false,
      todoProgress: null,
      extras: {},
    });

    // Invariant: outputs arrive out of order (tc-2 before tc-1) yet each lands
    // on its own tool call, and entry order is preserved.
    const byId = Object.fromEntries(
      acc.toolData.map((e) => {
        const d = e.data as { tool_call_id: string; output: string };
        return [d.tool_call_id, d.output];
      }),
    );
    expect(byId["tc-1"]).toBe("Found 3 results");
    expect(byId["tc-2"]).toBe("Email sent");
  });

  it("(c) subagent turn: reasoning routes into the group, nested subagent nests", () => {
    const acc = fold(subagentTurn);

    const nested: SubagentGroupData = {
      subagent_id: "sa-2",
      subagent_name: "Summarizer",
      agent_type: "spawned",
      tool_calls: [reasoningStep("Summarizing the thread.")],
      duration_ms: 1200,
      token_count: 345,
      started_at: "2026-01-01T00:00:01.000Z",
      completed_at: FIXED_NOW,
      icon_url: null,
      tool_category: null,
      nested_subagents: [],
    };

    const group: SubagentGroupData = {
      subagent_id: "sa-1",
      subagent_name: "Gmail Agent",
      agent_type: "handoff",
      tool_calls: [
        // Invariant: two reasoning deltas for sa-1 coalesce into one step.
        reasoningStep("Let me check your inbox."),
        {
          tool_name: "list_emails",
          tool_category: "gmail",
          message: "Listing emails",
          tool_call_id: "sa1-tc-1",
        },
      ],
      duration_ms: 5000,
      token_count: 900,
      started_at: "2026-01-01T00:00:00.000Z",
      completed_at: FIXED_NOW,
      icon_url: "https://cdn.example.com/gmail.png",
      tool_category: "gmail",
      nested_subagents: [nested],
    };

    expect(acc).toEqual({
      responseText: "All done.",
      currentMessageStart: 0,
      messageBreakPending: false,
      toolData: [
        {
          tool_name: "subagent_group",
          tool_category: "subagent",
          data: group,
          timestamp: "2026-01-01T00:00:00.000Z",
        },
      ],
      followUpActions: null,
      imageData: null,
      generatingImage: false,
      todoProgress: null,
      extras: {},
    });

    // Invariant: nesting depth is exactly 2 (sa-2 lives inside sa-1, no deeper).
    const rootGroup = acc.toolData[0].data as SubagentGroupData;
    expect(rootGroup.nested_subagents).toHaveLength(1);
    expect(rootGroup.nested_subagents[0].subagent_id).toBe("sa-2");
    expect(rootGroup.nested_subagents[0].nested_subagents).toHaveLength(0);
  });

  it("(d) todo_progress: accumulates by source, latest snapshot per source wins", () => {
    const acc = fold(todoProgress);

    const executorSnapshot: TodoProgressSnapshot = {
      source: "executor",
      todos: [
        { id: "t1", content: "Research topic", status: "completed" },
        { id: "t2", content: "Write summary", status: "in_progress" },
      ],
    };
    const subagentSnapshot: TodoProgressSnapshot = {
      source: "subagent:sa-1",
      todos: [{ id: "s1", content: "Fetch emails", status: "completed" }],
    };

    expect(acc).toEqual({
      responseText: "",
      currentMessageStart: 0,
      messageBreakPending: false,
      toolData: [
        {
          tool_name: "todo_progress",
          data: {
            executor: executorSnapshot,
            "subagent:sa-1": subagentSnapshot,
          },
          timestamp: FIXED_NOW,
        },
      ],
      followUpActions: null,
      imageData: null,
      generatingImage: false,
      todoProgress: {
        executor: executorSnapshot,
        "subagent:sa-1": subagentSnapshot,
      },
      extras: {},
    });

    // Invariant: the executor key holds the second (latest) snapshot, not the first.
    expect(acc.todoProgress?.executor.todos?.[0].status).toBe("completed");
  });

  it("(e) executor reasoning: consecutive deltas coalesce, a tool call splits blocks", () => {
    const acc = fold(executorReasoning);

    expect(acc).toEqual({
      responseText: "Answer.",
      currentMessageStart: 0,
      messageBreakPending: false,
      toolData: [
        {
          tool_name: "tool_calls_data",
          tool_category: "reasoning",
          data: [reasoningStep("First I think about the request.")],
          timestamp: FIXED_NOW,
        },
        {
          tool_name: "tool_calls_data",
          tool_category: "search",
          data: {
            tool_name: "web_search",
            tool_category: "search",
            message: "Searching",
            tool_call_id: "tc-1",
          },
        },
        {
          tool_name: "tool_calls_data",
          tool_category: "reasoning",
          data: [reasoningStep("Now I conclude.")],
          timestamp: FIXED_NOW,
        },
      ],
      followUpActions: null,
      imageData: null,
      generatingImage: false,
      todoProgress: null,
      extras: {},
    });

    // Invariant: exactly two reasoning blocks, split by the tool call between them.
    const reasoningBlocks = acc.toolData.filter((e) => Array.isArray(e.data));
    expect(reasoningBlocks).toHaveLength(2);
    expect((reasoningBlocks[0].data as unknown[]).length).toBe(1);
    expect((reasoningBlocks[1].data as unknown[]).length).toBe(1);
  });

  it("(f) image generation: generating_image status then image_data payload", () => {
    const acc = fold(imageGeneration);

    expect(acc).toEqual({
      // Invariant: the generating_image status clears any streamed text.
      responseText: "",
      currentMessageStart: 0,
      messageBreakPending: false,
      toolData: [],
      followUpActions: null,
      imageData: {
        url: "https://cdn.example.com/generated.png",
        prompt: "a cat astronaut",
      },
      generatingImage: false,
      todoProgress: null,
      extras: {},
    });
  });
});

describe("a retracted handoff preamble", () => {
  it("(g) is streamed, then cut back out when its message is discarded", () => {
    const acc = fold(discardedPreambleTurn);

    // In production the user read both: the preamble AND the acknowledgement,
    // concatenated into one bubble ("…tasks createdyeah, all of it's…").
    expect(acc.responseText).toBe("yeah, all of it's being set up now.");
    expect(acc.messageBreakPending).toBe(true);
  });

  it("shows the preamble while it is still the current message", () => {
    // The retraction is only possible AFTER the fact — the wire delivers a
    // message's text before its tool call. Withholding it instead would cost
    // every ordinary reply its token streaming.
    const acc = fold(discardedPreambleTurn.slice(0, 3));

    expect(acc.responseText).toBe(
      "yeah, i can set all that up. let me get the tasks created",
    );
  });

  it("separates two kept messages with the bubble-break sentinel", () => {
    const acc = fold([
      '{"response":"fixing it."}',
      '{"message_boundary":{"message_id":"m1","discarded":false}}',
      '{"response":"fixing it now."}',
      '{"message_boundary":{"message_id":"m2","discarded":false}}',
    ]);

    // Concatenating them is what produced the persisted "fixing it.fixing it now".
    expect(acc.responseText).toBe(
      `fixing it.${NEW_MESSAGE_BREAK_TOKEN}fixing it now.`,
    );
  });

  it("adds no separator for a message that carried no text", () => {
    const acc = fold([
      '{"response":"on it."}',
      '{"message_boundary":{"message_id":"m1","discarded":false}}',
      '{"message_boundary":{"message_id":"m2","discarded":false}}',
    ]);

    expect(acc.responseText).toBe("on it.");
  });

  it("never eats the text a resumed turn already had", () => {
    // The executor-resume transport seeds the accumulator with the message's
    // existing content. If the seed did not move currentMessageStart with it, a
    // discard in the resumed stream would cut that content away.
    const seeded = createTurnAccumulator("what the message already said. ");
    const acc = [
      '{"response":"and now some narration"}',
      '{"message_boundary":{"message_id":"m1","discarded":true}}',
    ]
      .flatMap((frame) => parseChatStreamEvent(frame))
      .reduce(applyStreamEvent, seeded);

    expect(acc.responseText).toBe("what the message already said. ");
  });
});

describe("turnAccumulator invariants", () => {
  it("replaces follow_up_actions rather than appending", () => {
    const acc = fold([
      '{"follow_up_actions":["one","two"]}',
      '{"follow_up_actions":["three"]}',
    ]);
    expect(acc.followUpActions).toEqual(["three"]);
  });

  it("routes unknown passthrough payloads into extras verbatim", () => {
    const acc = fold(['{"memory_data":{"operation":"search","count":2}}']);
    expect(acc.extras).toEqual({
      memory_data: { operation: "search", count: 2 },
    });
  });

  it("never mutates the input accumulator", () => {
    const acc0 = createTurnAccumulator();
    const frozenBaseline = createTurnAccumulator();

    const [responseEvent] = parseChatStreamEvent('{"response":"hi"}');
    const acc1 = applyStreamEvent(acc0, responseEvent);
    expect(acc1).not.toBe(acc0);
    expect(acc0).toEqual(frozenBaseline);

    const [toolEvent] = parseChatStreamEvent(
      '{"tool_data":{"tool_name":"weather_data","data":{"temperature":20}}}',
    );
    const acc2 = applyStreamEvent(acc0, toolEvent);
    expect(acc2.toolData).toHaveLength(1);
    // The original accumulator's array is untouched (new array, not push).
    expect(acc0.toolData).toHaveLength(0);
    expect(acc2.toolData).not.toBe(acc0.toolData);
  });
});
