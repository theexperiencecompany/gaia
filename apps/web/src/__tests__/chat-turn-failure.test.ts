/**
 * Regression tests for the chat failure surface.
 *
 * The bug: a turn that died client-side was persisted with `status: "failed"`
 * but no `error` string. Nothing reads `status`, and the failed-response bubble
 * keys off `error` — so the message rendered as empty, `filterEmptyMessagePairs`
 * dropped it from the thread entirely, and the only trace of the failure was a
 * transient toast. A stream that closed without its completion signal was worse:
 * it was persisted as `"sent"`, indistinguishable from a finished answer.
 *
 * These pin the three seams that chain together to put a failure on screen:
 * the record carries the error, the outcome rule classifies a truncated stream
 * as failed, and the empty-message filter keeps an errored turn in the thread.
 */
import { createTurnAccumulator, type TurnAccumulator } from "@shared/chat";
import { describe, expect, it, vi } from "vitest";
import {
  buildTurnMessageRecord,
  INTERRUPTED_ERROR,
  resolveTurnOutcome,
  type TurnMessageMeta,
} from "@/features/chat/stream/messageRecord";
import { StallWatchdog } from "@/features/chat/stream/stallWatchdog";
import {
  filterEmptyMessagePairs,
  isBotMessageEmpty,
} from "@/features/chat/utils/messageContentUtils";
import type { ChatBubbleBotProps } from "@/types/features/chatBubbleTypes";
import type { MessageType } from "@/types/features/convoTypes";

const meta = (): TurnMessageMeta => ({
  conversationId: "conv-1",
  botMessageId: "bot-1",
  createdAt: new Date("2026-01-01T00:00:00Z"),
  options: {
    fileData: [],
    selectedTool: null,
    toolCategory: null,
    selectedWorkflow: null,
    selectedCalendarEvent: null,
    replyToMessage: null,
    optimisticUserId: "user-1",
    conversationId: "conv-1",
    isOnboardingDemo: false,
  },
});

const accWithText = (text: string): TurnAccumulator => ({
  ...createTurnAccumulator(text),
});

describe("buildTurnMessageRecord", () => {
  it("carries the failure reason onto a failed record", () => {
    const record = buildTurnMessageRecord(
      meta(),
      createTurnAccumulator(),
      "failed",
      "Provider overloaded",
    );

    expect(record.status).toBe("failed");
    expect(record.error).toBe("Provider overloaded");
  });

  it("leaves error null on a successful record", () => {
    const record = buildTurnMessageRecord(
      meta(),
      accWithText("all good"),
      "sent",
    );

    expect(record.status).toBe("sent");
    expect(record.error).toBeNull();
  });

  it("keeps partial streamed text alongside the error on a truncated turn", () => {
    const record = buildTurnMessageRecord(
      meta(),
      accWithText("half an ans"),
      "failed",
      INTERRUPTED_ERROR,
    );

    expect(record.content).toBe("half an ans");
    expect(record.error).toBe(INTERRUPTED_ERROR);
  });
});

describe("resolveTurnOutcome", () => {
  it("marks a stream that never signalled completion as failed", () => {
    expect(resolveTurnOutcome(false)).toEqual({
      status: "failed",
      error: INTERRUPTED_ERROR,
    });
  });

  it("marks a stream that signalled completion as sent", () => {
    expect(resolveTurnOutcome(true)).toEqual({ status: "sent", error: null });
  });
});

describe("isBotMessageEmpty", () => {
  const props = (over: Partial<ChatBubbleBotProps>): ChatBubbleBotProps =>
    ({ text: "", message_id: "bot-1", ...over }) as ChatBubbleBotProps;

  it("treats an errored turn with no text as non-empty so it still renders", () => {
    expect(isBotMessageEmpty(props({ error: "boom" }))).toBe(false);
  });

  it("still treats a contentless, errorless turn as empty", () => {
    expect(isBotMessageEmpty(props({}))).toBe(true);
  });
});

describe("filterEmptyMessagePairs", () => {
  it("keeps a failed bot turn in the thread instead of dropping the pair", () => {
    const messages: MessageType[] = [
      { type: "user", response: "hi", message_id: "u-1" },
      { type: "bot", response: "", message_id: "b-1", error: "Provider down" },
    ];

    const kept = filterEmptyMessagePairs(messages);

    expect(kept.map((m) => m.message_id)).toEqual(["u-1", "b-1"]);
  });

  it("still drops a genuinely empty bot turn, keeping its user message", () => {
    const messages: MessageType[] = [
      { type: "user", response: "hi", message_id: "u-1" },
      { type: "bot", response: "", message_id: "b-1" },
    ];

    const kept = filterEmptyMessagePairs(messages);

    expect(kept.map((m) => m.message_id)).toEqual(["u-1"]);
  });
});

describe("StallWatchdog", () => {
  it("fires when no frame arrives within the idle window", () => {
    vi.useFakeTimers();
    const onStall = vi.fn();
    const watchdog = new StallWatchdog(1000, onStall);

    watchdog.arm();
    vi.advanceTimersByTime(999);
    expect(onStall).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);
    expect(onStall).toHaveBeenCalledTimes(1);

    watchdog.disarm();
    vi.useRealTimers();
  });

  it("does not fire while frames keep arriving", () => {
    vi.useFakeTimers();
    const onStall = vi.fn();
    const watchdog = new StallWatchdog(1000, onStall);

    watchdog.arm();
    for (let i = 0; i < 5; i++) {
      vi.advanceTimersByTime(900);
      watchdog.kick();
    }
    vi.advanceTimersByTime(900);
    expect(onStall).not.toHaveBeenCalled();

    watchdog.disarm();
    vi.useRealTimers();
  });

  it("stops firing once disarmed", () => {
    vi.useFakeTimers();
    const onStall = vi.fn();
    const watchdog = new StallWatchdog(1000, onStall);

    watchdog.arm();
    watchdog.disarm();
    vi.advanceTimersByTime(5000);

    expect(onStall).not.toHaveBeenCalled();
    vi.useRealTimers();
  });

  it("fires at most once per armed window", () => {
    vi.useFakeTimers();
    const onStall = vi.fn();
    const watchdog = new StallWatchdog(1000, onStall);

    watchdog.arm();
    vi.advanceTimersByTime(10_000);

    expect(onStall).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });
});
