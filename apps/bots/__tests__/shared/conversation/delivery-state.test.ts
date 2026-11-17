/**
 * The reply progress transition: what each send, hold and delivered report does
 * to the record the server keeps for a restarted follow.
 */
import { describe, expect, it } from "vitest";
import {
  nextProgress,
  type ProgressEvent,
  type ReplyProgress,
  recordOf,
  resumeProgress,
  untouchedReopened,
} from "../../../../../libs/shared/ts/src/bots/conversation/delivery-state";

const run = (start: ReplyProgress, events: ProgressEvent[]): ReplyProgress =>
  events.reduce(nextProgress, start);

const fresh = resumeProgress({ bubbles: 0, openMessageIds: [] });

describe("a reply's delivery progress", () => {
  it("records a send before it goes out with no id, and its id once it is out", () => {
    const sending = nextProgress(fresh, { kind: "sending", slot: 0 });
    expect(recordOf(sending)).toEqual({ bubbles: 0, openMessageIds: [null] });

    const sent = nextProgress(sending, { kind: "sent", slot: 0, id: "m1" });
    expect(recordOf(sent)).toEqual({ bubbles: 0, openMessageIds: ["m1"] });
  });

  it("refuses an id for a send that was never recorded", () => {
    expect(() =>
      nextProgress(fresh, { kind: "sent", slot: 0, id: "m1" }),
    ).toThrow("slot 0 was sent without being recorded");
  });

  it("closes every written message when the bubble is final, and keeps none open", () => {
    const delivered = run(fresh, [
      { kind: "sending", slot: 0 },
      { kind: "sent", slot: 0, id: "m1" },
      { kind: "sending", slot: 1 },
      { kind: "sent", slot: 1, id: "m2" },
      { kind: "delivered", bubbles: 1 },
    ]);
    expect(recordOf(delivered)).toEqual({ bubbles: 1, openMessageIds: [] });
  });

  it("resumes an earlier follow's open messages, drops its unconfirmed send, and leaves an unwritten one to delete", () => {
    const resumed = resumeProgress({
      bubbles: 2,
      openMessageIds: ["m7", "m8", null],
    });
    expect(recordOf(resumed)).toEqual({
      bubbles: 2,
      openMessageIds: ["m7", "m8"],
    });

    const written = run(resumed, [
      { kind: "held", slot: 0, text: "Part three, whole." },
      { kind: "delivered", bubbles: 3 },
    ]);
    expect(recordOf(written)).toEqual({ bubbles: 3, openMessageIds: ["m8"] });
    expect(untouchedReopened(written)).toEqual([[1, "m8"]]);
  });

  it("holds text only for a message an earlier follow left open", () => {
    const shown = run(fresh, [
      { kind: "sending", slot: 0 },
      { kind: "sent", slot: 0, id: "m1" },
    ]);
    expect(() =>
      nextProgress(shown, { kind: "held", slot: 0, text: "more" }),
    ).toThrow("slot 0 is not a reopened message");
  });
});
