import { describe, expect, it } from "vitest";

import type { IMessage } from "@/lib/db/chatDb";
import { ACCEPTED_MESSAGE_KIND, isWorkAnswered } from "./workChip";

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

describe("isWorkAnswered", () => {
  const accepted = message("a", { kind: ACCEPTED_MESSAGE_KIND });

  it("is false while nothing has followed the accepted turn", () => {
    expect(
      isWorkAnswered([message("u", { role: "user" }), accepted], "a"),
    ).toBe(false);
  });

  it("is true once a later assistant message has words", () => {
    expect(
      isWorkAnswered([accepted, message("r", { content: "Sent it." })], "a"),
    ).toBe(true);
  });

  it("ignores a later silent turn and a reaction", () => {
    expect(
      isWorkAnswered(
        [
          accepted,
          message("b", { kind: ACCEPTED_MESSAGE_KIND }),
          message("c", { content: "👍", kind: "emoji_ack" }),
        ],
        "a",
      ),
    ).toBe(false);
  });

  it("ignores messages from before the accepted turn", () => {
    expect(
      isWorkAnswered([message("old", { content: "earlier" }), accepted], "a"),
    ).toBe(false);
  });

  it("is false for a turn that is not in the list", () => {
    expect(isWorkAnswered([accepted], "missing")).toBe(false);
  });
});
