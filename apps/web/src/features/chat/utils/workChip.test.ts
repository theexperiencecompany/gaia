import type { WorkRunOutcome } from "@shared/api/generated";
import { describe, expect, it } from "vitest";
import type { IMessage } from "@/lib/db/chatDb";
import { SettledOutcome } from "@/lib/websocket/outboxEvents";
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

const run = (report_id: string, outcome: WorkRunOutcome["outcome"]) => ({
  report_id,
  outcome,
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
      { ...accepted, workOutcomes: [run("r1", SettledOutcome.Failed)] },
      message("r", { content: "Another run's answer." }),
    ];
    expect(workChipState(answeredElsewhere, "a")).toBe("failed");
  });

  it.each([
    [SettledOutcome.DeliveredHere, "done"],
    [SettledOutcome.DeliveredElsewhere, "done"],
    [SettledOutcome.Recorded, "nothing_new"],
    [SettledOutcome.Failed, "failed"],
  ] as const)(
    "settles on %s with no text in the conversation",
    (outcome, state) => {
      expect(
        workChipState(
          [{ ...accepted, workOutcomes: [run("r1", outcome)] }],
          "a",
        ),
      ).toBe(state);
    },
  );

  it("reads as the worst of the runs a turn started", () => {
    const outcomesOf = (...runs: WorkRunOutcome[]) =>
      workChipState([{ ...accepted, workOutcomes: runs }], "a");

    expect(
      outcomesOf(
        run("r1", SettledOutcome.DeliveredHere),
        run("r2", SettledOutcome.Failed),
      ),
    ).toBe("failed");
    expect(
      outcomesOf(
        run("r1", SettledOutcome.Recorded),
        run("r2", SettledOutcome.DeliveredElsewhere),
      ),
    ).toBe("done");
    expect(
      outcomesOf(
        run("r1", SettledOutcome.Recorded),
        run("r2", SettledOutcome.Recorded),
      ),
    ).toBe("nothing_new");
  });
});
