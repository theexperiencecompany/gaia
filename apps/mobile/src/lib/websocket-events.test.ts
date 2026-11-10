import { describe, expect, it } from "vitest";
import { isOutboxNotification, WS_EVENTS } from "./websocket-events";

describe("isOutboxNotification", () => {
  it("accepts an outbox frame carrying a notification", () => {
    expect(
      isOutboxNotification({
        type: WS_EVENTS.OUTBOX_MESSAGE,
        kind: "notification",
        notification: { id: "n-1" },
      }),
    ).toBe(true);
  });

  it("rejects an outbox frame carrying a chat message", () => {
    expect(
      isOutboxNotification({
        type: WS_EVENTS.OUTBOX_MESSAGE,
        kind: "conversation_message",
        conversation_id: "c-1",
      }),
    ).toBe(false);
  });

  it("rejects a frame with no kind and non-object payloads", () => {
    expect(isOutboxNotification({ type: WS_EVENTS.OUTBOX_MESSAGE })).toBe(
      false,
    );
    expect(isOutboxNotification(null)).toBe(false);
    expect(isOutboxNotification("notification")).toBe(false);
  });
});
