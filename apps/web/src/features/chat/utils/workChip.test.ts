import { describe, expect, it } from "vitest";

import type { IMessage } from "@/lib/db/chatDb";
import { ReportSettledOutcome } from "@/lib/websocket/outboxEvents";
import { ACCEPTED_MESSAGE_KIND, workChipState } from "./workChip";

const message = (id: string, over: Partial<IMessage> = {}): IMessage => ({
  id,
  conversationId: "c1",
  content: "",
  role: "assistant",
  status: "sent",
  createdAt: new Date(0),
  updatedAt: new Date(0),
  ...over,
});

describe("workChipState", () => {
  const accepted = message("a", { kind: ACCEPTED_MESSAGE_KIND });

  it("is working while nothing has followed the accepted turn", () => {
    expect(workChipState([message("u", { role: "user" }), accepted], "a")).toBe(
      "working",
    );
  });

  it("is done once a later assistant message has words and no outcome is known", () => {
    expect(
      workChipState([accepted, message("r", { content: "Sent it." })], "a"),
    ).toBe("done");
  });

  it("ignores a later silent turn and a reaction", () => {
    expect(
      workChipState(
        [
          accepted,
          message("b", { kind: ACCEPTED_MESSAGE_KIND }),
          message("c", { content: "👍", kind: "emoji_ack" }),
        ],
        "a",
      ),
    ).toBe("working");
  });

  it("ignores messages from before the accepted turn", () => {
    expect(
      workChipState([message("old", { content: "earlier" }), accepted], "a"),
    ).toBe("working");
  });

  it("is working for a turn that is not in the list", () => {
    expect(workChipState([accepted], "missing")).toBe("working");
  });

  it("follows the outcome of its own run, not another run's answer", () => {
    const answeredElsewhere = [
      { ...accepted, workOutcome: ReportSettledOutcome.Failed },
      message("r", { content: "Another run's answer." }),
    ];
    expect(workChipState(answeredElsewhere, "a")).toBe("failed");
  });

  it.each([
    [ReportSettledOutcome.DeliveredHere, "done"],
    [ReportSettledOutcome.DeliveredElsewhere, "done"],
    [ReportSettledOutcome.Recorded, "nothing_new"],
    [ReportSettledOutcome.Failed, "failed"],
  ] as const)(
    "settles on %s with no text in the conversation",
    (outcome, state) => {
      expect(workChipState([{ ...accepted, workOutcome: outcome }], "a")).toBe(
        state,
      );
    },
  );
});
