import { describe, expect, it } from "vitest";
import type { IMessage } from "./chatDb";
import { compareMessageOrder } from "./messageOrder";

const message = (
  id: string,
  createdAt: string,
  overrides: Partial<IMessage> = {},
): IMessage => ({
  id,
  conversationId: "conv",
  content: id,
  role: "user",
  status: "sent",
  createdAt: new Date(createdAt),
  updatedAt: new Date(createdAt),
  ...overrides,
});

const order = (messages: IMessage[]) =>
  messages.toSorted(compareMessageOrder).map((m) => m.id);

describe("compareMessageOrder", () => {
  it("orders placed messages by seq, never by their dates", () => {
    expect(
      order([
        message("b", "2026-01-01T10:00:00Z", { seq: 3 }),
        message("reply", "2026-01-01T10:05:00Z", { seq: 2 }),
        message("a", "2026-01-01T09:00:00Z", { seq: 1 }),
      ]),
    ).toEqual(["a", "reply", "b"]);
  });

  it("puts messages the server has not placed after every placed one, in creation order", () => {
    expect(
      order([
        message("queued", "2026-01-01T09:02:00Z", { status: "queued" }),
        message("placed", "2026-01-01T12:00:00Z", { seq: 7 }),
        message("optimistic", "2026-01-01T09:01:00Z", {
          optimistic: true,
          status: "sending",
        }),
        message("live-reply", "2026-01-01T09:00:00Z", {
          role: "assistant",
          status: "sending",
        }),
      ]),
    ).toEqual(["placed", "live-reply", "optimistic", "queued"]);
  });

  it("moves a message into its place when its seq arrives", () => {
    const pending = message("reply", "2026-01-01T09:00:00Z", {
      role: "assistant",
      status: "sending",
    });
    const later = message("b", "2026-01-01T08:00:00Z", { seq: 3 });
    const first = message("a", "2026-01-01T07:00:00Z", { seq: 1 });

    expect(order([pending, later, first])).toEqual(["a", "b", "reply"]);
    expect(order([{ ...pending, seq: 2 }, later, first])).toEqual([
      "a",
      "reply",
      "b",
    ]);
  });

  it("keeps messages cached before seq existed ahead of placed ones, in their old order", () => {
    expect(
      order([
        message("new", "2026-01-01T08:00:00Z", { seq: 41 }),
        message("cached-2", "2026-01-01T09:00:00Z"),
        message("cached-1", "2026-01-01T08:30:00Z"),
      ]),
    ).toEqual(["cached-1", "cached-2", "new"]);
  });
});
