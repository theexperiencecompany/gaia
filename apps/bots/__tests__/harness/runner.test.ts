/**
 * Unit tests for the scenario runner's turn delivery and transcript assertions,
 * against hand-recorded transcripts and a fake adapter (no API).
 */

import { describe, expect, it } from "vitest";
import type { HarnessAdapter } from "../../harness/src/adapter";
import { deliverTurn, evaluateAssertion } from "../../harness/src/runner";
import { TranscriptRecorder } from "../../harness/src/transcript";
import type { TranscriptEventInput } from "../../harness/src/transcript.types";

function transcript(...inputs: TranscriptEventInput[]) {
  const recorder = new TranscriptRecorder("telegram");
  for (const input of inputs) recorder.record(input);
  return recorder.getEvents();
}

const inbound = (messageId: string, text: string): TranscriptEventInput => ({
  type: "inbound",
  userId: "u",
  channelId: "u",
  messageId,
  text,
});
const send = (messageId: string, text: string): TranscriptEventInput => ({
  type: "send",
  messageId,
  text,
  length: text.length,
});
const edit = (messageId: string, text: string): TranscriptEventInput => ({
  type: "edit",
  messageId,
  text,
  length: text.length,
});

describe("evaluateAssertion — delivered", () => {
  const events = transcript(
    inbound("in1", "first"),
    send("m1", "Work"),
    send("m2", "Quick answer"),
    edit("m1", "Working on it"),
    { type: "outbound-delivery", destinationId: "u", text: "All done" },
  );

  it("holds for each message's final text in first-appearance order", () => {
    expect(
      evaluateAssertion(events, {
        delivered: ["Working on", "Quick", "All done"],
      }),
    ).toEqual([]);
  });

  it("fails on the same messages in another order", () => {
    expect(
      evaluateAssertion(events, {
        delivered: ["Quick", "Working on", "All done"],
      }),
    ).toHaveLength(1);
  });

  it("fails when a message is missing from the expectation", () => {
    expect(
      evaluateAssertion(events, { delivered: ["Working on", "Quick"] }),
    ).toEqual([
      'expected delivered ["Working on","Quick"], got ["Working on it","Quick answer","All done"]',
    ]);
  });

  it("bubbles leaves the proactive delivery out of the order", () => {
    expect(
      evaluateAssertion(events, { bubbles: ["Working on", "Quick"] }),
    ).toEqual([]);
    expect(
      evaluateAssertion(events, {
        bubbles: ["Working on", "Quick", "All done"],
      }),
    ).toHaveLength(1);
  });

  it("checks a bubble's last edit, not its first text", () => {
    const edited = transcript(send("m1", "Draft"), edit("m1", "Final"));
    expect(evaluateAssertion(edited, { delivered: ["Final"] })).toEqual([]);
    expect(evaluateAssertion(edited, { delivered: ["Draft"] })).toHaveLength(1);
  });
});

describe("evaluateAssertion — reactedTo", () => {
  const events = transcript(
    inbound("in1", "one"),
    inbound("in2", "two"),
    inbound("in3", "three"),
    {
      type: "reaction",
      destinationId: "u",
      targetMessageId: "in2",
      emoji: "👍",
    },
  );

  it("names the reacted message by its position in the turn", () => {
    expect(evaluateAssertion(events, { reactedTo: [2] })).toEqual([]);
  });

  it("fails when the reaction is on another message", () => {
    expect(evaluateAssertion(events, { reactedTo: [1] })).toEqual([
      "expected reactions on inbound [1], got [2]",
    ]);
  });

  it("asserts no reactions with an empty list", () => {
    expect(evaluateAssertion(events, { reactedTo: [] })).toHaveLength(1);
    expect(
      evaluateAssertion(transcript(inbound("in1", "one")), { reactedTo: [] }),
    ).toEqual([]);
  });
});

describe("deliverTurn", () => {
  function recordingAdapter() {
    const arrivals: Array<{ text: string; at: number }> = [];
    const started = Date.now();
    const adapter = {
      simulateMessage: (_user: string, text: string) => {
        arrivals.push({ text, at: Date.now() - started });
        return new Promise<void>((resolve) => setTimeout(resolve, 50));
      },
    } as unknown as HarnessAdapter;
    return { adapter, arrivals };
  }

  it("sends a burst at its gaps without waiting for the replies", async () => {
    const { adapter, arrivals } = recordingAdapter();
    await deliverTurn(adapter, "u", {
      burst: [
        { send: "one" },
        { send: "two", afterMs: 10 },
        { send: "three", afterMs: 10 },
      ],
    });
    expect(arrivals.map((a) => a.text)).toEqual(["one", "two", "three"]);
    // Each reply takes 50ms, so an arrival gated on the previous reply lands past it.
    expect(arrivals[2].at).toBeLessThan(50);
    expect(arrivals[1].at).toBeGreaterThanOrEqual(10);
  });

  it("rejects a turn that sets both send and burst, or neither", async () => {
    const { adapter } = recordingAdapter();
    await expect(
      deliverTurn(adapter, "u", { send: "x", burst: [{ send: "y" }] }),
    ).rejects.toThrow("exactly one of `send` and `burst`");
    await expect(deliverTurn(adapter, "u", {})).rejects.toThrow(
      "exactly one of `send` and `burst`",
    );
    await expect(deliverTurn(adapter, "u", { burst: [] })).rejects.toThrow(
      "at least one message",
    );
  });
});
