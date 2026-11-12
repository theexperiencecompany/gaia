/**
 * Delivery tests for the shared bot streamer (`handleStreamingChat`).
 *
 * These drive the REAL `_handleStream` — the adapter test suites all replace it
 * with `vi.fn()`, which is why every bug below shipped green. The only fake here
 * is the `GaiaClient` stream source and the platform send/edit callbacks, which
 * stand in for the platform SDK exactly as each adapter wires them.
 */
import type { ApprovalRequestData } from "@gaia/shared";
import {
  BUBBLE_PAUSE_MS,
  type GaiaClient,
  handleStreamingChat,
  PLATFORM_LIMITS,
  type PlatformName,
  renderForPlatform,
  STREAMING_DEFAULTS,
} from "@gaia/shared/bots";
import { describe, expect, it } from "vitest";

const BREAK = "<NEW_MESSAGE_BREAK>";

/** A reply body of roughly `sentences * 42` characters. */
function body(word: string, sentences: number): string {
  return Array.from(
    { length: sentences },
    (_, i) => `${word} segment sentence number ${i} here. `,
  ).join("");
}

/**
 * A GaiaClient stub that streams `chunks` in order, then completes.
 *
 * Cast through `unknown` rather than `any`: the streamer only ever touches
 * `chatStream` and `createLinkToken`, so implementing the whole client would be
 * noise, but the cast stays explicit instead of disabling the lint rule.
 */
/**
 * A scripted stream step: text to emit, a message boundary from the API, or an
 * out-of-band notice (the rate-limit warning).
 */
type StreamStep =
  | string
  | { boundary: { discarded: boolean } }
  | { notice: string }
  | { waitMs: number }
  | { fail: string };

/** The style guard's retraction frame, and the kept boundary that ends a message. */
const DISCARDED = { boundary: { discarded: true } } as const;
const KEPT = { boundary: { discarded: false } } as const;

function streamingGaia(
  chunks: StreamStep[],
  approvalAfter?: number,
  approval?: Partial<ApprovalRequestData>,
): GaiaClient {
  return {
    chatStream: async (
      _request: unknown,
      onChunk: (text: string) => void | Promise<void>,
      onDone: (
        fullText: string,
        conversationId: string,
      ) => void | Promise<void>,
      onError: (error: Error) => void | Promise<void>,
      onApproval?: (data: ApprovalRequestData) => void | Promise<void>,
      onBoundary?: (discarded: boolean) => void | Promise<void>,
      onNotice?: (text: string) => void | Promise<void>,
    ) => {
      // Mirrors chat-stream.ts: streamed text only joins `fullText` once its
      // message is confirmed kept, so a discarded preamble never reaches the
      // platforms that render from `fullText` alone.
      let full = "";
      let pendingText = "";
      const keepPendingText = (): void => {
        if (!pendingText) return;
        full = full ? `${full}${BREAK}${pendingText}` : pendingText;
        pendingText = "";
      };
      for (const [i, step] of chunks.entries()) {
        if (typeof step !== "string") {
          if ("fail" in step) {
            await onError(new Error(step.fail));
            return full;
          }
          if ("waitMs" in step) {
            await new Promise((resolve) => setTimeout(resolve, step.waitMs));
            continue;
          }
          if ("notice" in step) {
            await onNotice?.(step.notice);
            continue;
          }
          if (step.boundary.discarded) {
            pendingText = "";
          } else {
            keepPendingText();
          }
          await onBoundary?.(step.boundary.discarded);
          continue;
        }
        pendingText += step;
        await onChunk(step);
        if (approvalAfter === i && onApproval) {
          await onApproval({
            approval_id: "a1",
            tool_call_id: "t1",
            gated_tool_name: "delete_everything",
            integration_name: null,
            summary: "Delete the production database",
            args_preview: {},
            status: "pending",
            feedback: null,
            timeout_seconds: 3600,
            ...approval,
          } as ApprovalRequestData);
        }
      }
      keepPendingText();
      await onDone(full, "conv-test");
      return full;
    },
    createLinkToken: async () => ({ authUrl: "https://gaia.test/link" }),
  } as unknown as GaiaClient;
}

/**
 * A GaiaClient whose stream fails the way `streamChat` does for a
 * non-retryable transport error: report it through `onError`, then rethrow.
 */
function failingGaia(error: unknown): GaiaClient {
  return {
    chatStream: async (
      _request: unknown,
      _onChunk: unknown,
      _onDone: unknown,
      onError: (e: Error) => void | Promise<void>,
    ) => {
      await onError(error as Error);
      throw error;
    },
    createLinkToken: async () => ({ authUrl: "https://gaia.test/link" }),
  } as unknown as GaiaClient;
}

interface Delivered {
  /** Final text of every message still on screen, in the order each was opened. */
  bubbles: string[];
  /** Every distinct text the platform was ever asked to display. */
  writes: string[];
  /** How many brand-new messages the platform was asked to post. */
  newMessages: number;
  /** Every formatted error the platform was asked to show. */
  errors: string[];
  /** Every state the screen passed through, one entry per platform call. */
  frames: string[][];
  /** When each frame appeared, epoch ms. */
  times: number[];
}

/**
 * Runs one streamed turn against a platform, emulating that platform's real
 * wiring: `editMessage` edits the placeholder, each new message is a handle of
 * its own, editable platforms edit in place and non-editable ones (WhatsApp,
 * iMessage) turn every edit into a new message. Live platforms can delete.
 */
async function deliver(
  platform: PlatformName,
  chunks: StreamStep[],
  {
    editable = true,
    approvalAfter,
    approval,
    failEdit,
    failStream,
  }: {
    editable?: boolean;
    approvalAfter?: number;
    approval?: Partial<ApprovalRequestData>;
    /** Throws on the Nth edit (0-based), emulating a platform rejection. */
    failEdit?: { at: number; error: unknown };
    /** The transport error to fail the whole stream with, instead of streaming. */
    failStream?: unknown;
  } = {},
): Promise<Delivered> {
  /** Every message posted, `null` once deleted; index 0 is the placeholder once written. */
  const screen: (string | null)[] = [];
  const writes: string[] = [];
  const errors: string[] = [];
  const frames: string[][] = [];
  const times: number[] = [];
  let placeholder = -1;
  let editAttempts = 0;
  let newMessages = 0;

  const snapshot = (): void => {
    frames.push(screen.filter((m): m is string => m !== null));
    times.push(Date.now());
  };
  const maybeFail = (): void => {
    if (failEdit && editAttempts === failEdit.at) {
      editAttempts += 1;
      throw failEdit.error;
    }
    editAttempts += 1;
  };
  const post = (text: string): number => {
    writes.push(text);
    screen.push(text);
    snapshot();
    return screen.length - 1;
  };
  const write = (index: number, text: string): void => {
    writes.push(text);
    if (editable) {
      screen[index] = text;
      snapshot();
      return;
    }
    post(text);
  };

  const editMessage = async (text: string): Promise<void> => {
    maybeFail();
    if (placeholder === -1) {
      placeholder = post(text);
      return;
    }
    write(placeholder, text);
  };

  const sendNewMessage = async (text: string) => {
    newMessages += 1;
    const index = post(text);
    return {
      edit: async (updated: string): Promise<void> => {
        maybeFail();
        write(index, updated);
      },
      ...(STREAMING_DEFAULTS[platform].streaming
        ? {
            delete: async (): Promise<void> => {
              screen[index] = null;
              snapshot();
            },
          }
        : {}),
    };
  };

  await handleStreamingChat(
    failStream === undefined
      ? streamingGaia(chunks, approvalAfter, approval)
      : failingGaia(failStream),
    {
      message: "drive the streamer",
      platform,
      platformUserId: "u1",
      channelId: "c1",
    },
    editMessage,
    sendNewMessage,
    async () => {
      throw new Error("auth error path is not exercised by these cases");
    },
    async (formattedError: string) => {
      errors.push(formattedError);
      if (failStream === undefined) {
        throw new Error(`unexpected stream error: ${formattedError}`);
      }
    },
    STREAMING_DEFAULTS[platform],
    undefined,
    undefined,
    // A live adapter's no-reply handler deletes its placeholder; nothing else has one.
    STREAMING_DEFAULTS[platform].streaming
      ? async () => {
          if (placeholder === -1) return;
          screen[placeholder] = null;
          snapshot();
        }
      : undefined,
  );

  return {
    bubbles: screen.filter((m): m is string => m !== null),
    writes,
    newMessages,
    errors,
    frames,
    times,
  };
}

/**
 * Fails when any text the user could read left the screen: every message in a
 * frame must still be there, at least as long, in the next frame.
 */
function expectNothingVanishes(frames: string[][]): void {
  for (const [i, frame] of frames.entries()) {
    const next = frames[i + 1];
    if (!next) continue;
    const shown = frame.join("\n\n").replace(/\s+/g, " ").trim();
    const after = next.join("\n\n").replace(/\s+/g, " ").trim();
    expect(after.startsWith(shown), `frame ${i}: ${shown}\n-> ${after}`).toBe(
      true,
    );
  }
}

/** Word count, so text is compared by content rather than exact whitespace. */
function words(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

// Each is a message on its own: a segment under 40 characters is glued to its neighbour.
const GREETING = "Hey there, I just looked into this for you.";
const CHECKED = "I checked your calendar for the whole of next week.";
const ANSWER = "You are free at 3pm on Tuesday and all of Thursday.";

describe("handleStreamingChat delivery", () => {
  describe("a trailing break token must not swallow the reply", () => {
    // The model routinely ends a reply with a break token. The live-edit path
    // used to consume it, empty its buffer, and leave final delivery with
    // nothing to send — so the user kept whatever truncated text was on screen.
    it.each<PlatformName>(["telegram", "slack"])(
      "%s delivers the whole reply",
      async (platform) => {
        const text = body("Alpha", 120);
        const { bubbles } = await deliver(platform, [text, BREAK]);

        expect(bubbles.join(" ")).not.toContain("(truncated)");
        expect(words(bubbles.join(" "))).toBe(words(text));
        expect(bubbles.length).toBeGreaterThan(1);
      },
    );
  });

  describe("every bubble fits the platform limit once rendered", () => {
    it.each<PlatformName>(["telegram", "slack", "discord", "whatsapp"])(
      "%s",
      async (platform) => {
        const text = body("Alpha", 200);
        const { writes } = await deliver(platform, [text, BREAK]);

        for (const write of writes) {
          expect(write.length).toBeLessThanOrEqual(PLATFORM_LIMITS[platform]);
        }
      },
    );

    // Telegram receives HTML, not markdown: `**a**` becomes `<b>a</b>` and `&`
    // becomes `&amp;`. Sizing chunks by their raw markdown length let a bubble
    // render past 4096 and be rejected by the API.
    it("telegram sizes bubbles by rendered HTML, not raw markdown", async () => {
      const text = Array.from(
        { length: 90 },
        (_, i) =>
          `**Bold & bright ${i}** — see [the docs](https://example.com/a/b/c) <now>. `,
      ).join("");

      const { writes } = await deliver("telegram", [text, BREAK]);

      expect(writes.length).toBeGreaterThan(1);
      for (const write of writes) {
        expect(write.length).toBeLessThanOrEqual(4096);
      }
      // The callbacks receive already-rendered text, so this is what the API sees.
      expect(writes.some((w) => w.includes("<b>"))).toBe(true);
    });
  });

  describe("break tokens split bubbles on every platform", () => {
    it.each<PlatformName>(["telegram", "slack", "discord", "whatsapp"])(
      "%s emits one bubble per segment",
      async (platform) => {
        const { bubbles } = await deliver(platform, [
          GREETING,
          BREAK,
          CHECKED,
          BREAK,
          ANSWER,
        ]);

        expect(bubbles).toEqual([
          renderForPlatform(GREETING, platform),
          renderForPlatform(CHECKED, platform),
          renderForPlatform(ANSWER, platform),
        ]);
      },
    );

    it("keeps every long segment whole across its own bubbles", async () => {
      const first = body("Alpha", 120);
      const second = body("Beta", 120);

      const { bubbles } = await deliver("telegram", [
        first,
        BREAK,
        second,
        BREAK,
      ]);

      const delivered = bubbles.join(" ");
      expect(delivered).not.toContain("(truncated)");
      expect(words(delivered)).toBe(words(first) + words(second));
    });
  });

  it("does not overwrite an out-of-band approval prompt", async () => {
    // The approval prompt posts via the adapter's `sendNewMessage`, moving that
    // adapter's live-edit cursor onto the prompt on editing platforms; if the
    // streamer kept editing "the current message" it'd overwrite the question.
    const { bubbles } = await deliver(
      "telegram",
      ["Checking that first. ", "Now the rest of the answer."],
      { approvalAfter: 0 },
    );

    const prompt = bubbles.find((b) => b.includes("Approval needed"));
    expect(prompt).toBeDefined();
    expect(prompt).toContain("Delete the production database");
    // Whatever streamed after the prompt must land in its own message.
    expect(bubbles.at(-1)).toContain("Now the rest of the answer");
    expect(bubbles.at(-1)).not.toContain("Approval needed");
  });

  it("shows how long ago the approval was asked", async () => {
    // Ledger-backed approvals carry age_seconds; the prompt should surface it
    // so a user answering hours later knows the request is stale.
    const { bubbles } = await deliver("telegram", ["Checking that first. "], {
      approvalAfter: 0,
      approval: { age_seconds: 3700 },
    });

    const prompt = bubbles.find((b) => b.includes("Approval needed"));
    expect(prompt).toBeDefined();
    expect(prompt).toContain("asked 1h ago");
  });

  it("never shows a break token, whole or partially received", async () => {
    // The 18-char token arrives split across stream chunks; a half-received
    // `<NEW_MESSAG` must not flash in the bubble (and on Telegram an unclosed
    // `<` breaks the HTML parse for the whole edit).
    const { writes } = await deliver("telegram", [
      "Checking that now.",
      "<NEW_MESS",
      "AGE_BREAK>",
      "All done.",
    ]);

    for (const write of writes) {
      expect(write).not.toContain("NEW_MESS");
      expect(write).not.toContain("<NEW");
    }
  });

  it("treats the <NEW_LINE_BREAK> variant as a bubble break, never literal text", async () => {
    // The model sometimes emits <NEW_LINE_BREAK> instead of the canonical
    // <NEW_MESSAGE_BREAK>. Only the exact token was split on, so the variant
    // shipped to Telegram as literal text.
    const { bubbles } = await deliver("telegram", [
      GREETING,
      "<NEW_LINE_BREAK>",
      CHECKED,
    ]);

    expect(bubbles).toEqual([
      renderForPlatform(GREETING, "telegram"),
      renderForPlatform(CHECKED, "telegram"),
    ]);
  });

  it("never shows a partial <NEW_LINE_BREAK> variant", async () => {
    const { writes } = await deliver("telegram", [
      "Checking that now.",
      "<NEW_LINE_BRE",
      "AK>",
      "All done.",
    ]);

    for (const write of writes) {
      expect(write).not.toContain("NEW_LINE");
      expect(write).not.toContain("<NEW");
    }
  });

  it("never shows a partial lowercase or spaced variant either", async () => {
    // Normalization matches case/whitespace variants of complete tokens; the
    // live-preview strip must recognize their PARTIALS too, or a chunk
    // boundary inside "<new_line_br" flashes literal text.
    const { bubbles, writes } = await deliver("telegram", [
      "Checking that now.",
      "<new_line_br",
      "eak>",
      "All ",
      "< NEW_MESS",
      "AGE_BREAK>",
      "done.",
    ]);

    for (const write of writes) {
      const lowered = write.toLowerCase();
      expect(lowered).not.toContain("new_line");
      expect(lowered).not.toContain("new_mess");
      expect(write).not.toContain("<");
    }
    // Both sides of each variant survived as real bubbles.
    expect(bubbles.join("\n")).toContain("All");
    expect(bubbles.join("\n")).toContain("done.");
  });

  it("delivers the full reply on platforms that cannot edit", async () => {
    // WhatsApp/iMessage have no edit API, so each write is a new message.
    const text = body("Alpha", 120);
    const { bubbles } = await deliver("whatsapp", [text, BREAK], {
      editable: false,
    });

    expect(bubbles.join(" ")).not.toContain("(truncated)");
    expect(words(bubbles.join(" "))).toBe(words(text));
  });

  it("delivers a reply whose last chunk is a half-received break token", async () => {
    // Every partial-token case above is followed by more text, which hides the
    // fragment. When the stream ENDS mid-token there is no later chunk to hide
    // it: the fragment is the last thing the user reads.
    const { bubbles, writes } = await deliver("telegram", [
      "here are your numbers",
      "<NEW_MESSAGE_B",
    ]);

    expect(bubbles.join("\n")).toBe(
      renderForPlatform("here are your numbers", "telegram"),
    );
    for (const write of writes) {
      expect(write).not.toContain("NEW_MESSAGE");
      expect(write).not.toContain("<");
    }
  });

  it.each([
    ["bracketed", "[NEW_MESSAGE_BREAK]"],
    ["closing-tag", "</NEW_MESSAGE_BREAK>"],
    ["self-closing", "<NEW_MESSAGE_BREAK/>"],
    ["spaced words", "<NEW MESSAGE BREAK>"],
    ["hyphenated", "<NEW-MESSAGE-BREAK>"],
  ])("splits on the %s sentinel variant", async (_name, token) => {
    const { bubbles } = await deliver("telegram", [
      "First message, long enough to stand on its own here.",
      token,
      "Second message, long enough to stand on its own here.",
    ]);

    expect(bubbles).toEqual([
      renderForPlatform(
        "First message, long enough to stand on its own here.",
        "telegram",
      ),
      renderForPlatform(
        "Second message, long enough to stand on its own here.",
        "telegram",
      ),
    ]);
  });

  it("retries a rate-limited edit instead of re-sending the whole reply", async () => {
    // Any edit failure used to post the full text as a NEW message, double-delivering
    // on a 429 with the original bubble still on screen. Discord streams nothing
    // mid-flight, so the final edit is the one that used to double-post.
    const { bubbles, newMessages } = await deliver(
      "discord",
      ["Here is the answer you asked for, in full."],
      {
        failEdit: {
          at: 0,
          error: Object.assign(new Error("Too Many Requests: retry after 0"), {
            error_code: 429,
            parameters: { retry_after: 0 },
          }),
        },
      },
    );

    expect(newMessages).toBe(0);
    expect(bubbles).toEqual([
      renderForPlatform(
        "Here is the answer you asked for, in full.",
        "discord",
      ),
    ]);
  });

  it("opens a new message only when the old one is gone", async () => {
    const { bubbles, newMessages } = await deliver(
      "discord",
      ["Here is the answer you asked for, in full."],
      {
        failEdit: {
          at: 0,
          error: new Error("Bad Request: message to edit not found"),
        },
      },
    );

    expect(newMessages).toBe(1);
    expect(bubbles.at(-1)).toContain("Here is the answer");
  });

  it("replaces a retracted handoff preamble in place", async () => {
    // The comms agent narrates its own handoff, and the backend retracts that
    // message once the tool call shows up — the user must end with ONE message
    // holding the real reply, not the preamble plus a repeat.
    const { bubbles, newMessages } = await deliver("telegram", [
      "yeah, i can set all that up. let me get the tasks created",
      DISCARDED,
      "yeah, all of it's being set up now.",
    ]);

    expect(newMessages).toBe(0);
    expect(bubbles).toEqual([
      renderForPlatform("yeah, all of it's being set up now.", "telegram"),
    ]);
  });

  describe("a style-guard regeneration delivers only the rewrite", () => {
    // Live on Telegram this shipped the reply twice: draft segments sealed as
    // their own messages while streaming, so retraction (reopens only the ONE
    // bubble being edited) left every draft bubble plus a fresh rewrite underneath (9+10=19 msgs).
    const DRAFT: StreamStep[] = [
      "Hey — I've gone ahead and looked at all of this for you.",
      BREAK,
      "First, the calendar: you have three meetings tomorrow.\n\n" +
        "Second, the inbox: forty-two unread, eight of them flagged.",
      BREAK,
      "Let me know if you want me to reschedule anything at all.",
    ];
    const REWRITE: StreamStep[] = [
      "looked at all of it, here's where things stand for you.",
      BREAK,
      "three meetings tomorrow, and 42 unread with 8 of them flagged.",
    ];
    const REWRITE_BUBBLES = [
      "looked at all of it, here's where things stand for you.",
      "three meetings tomorrow, and 42 unread with 8 of them flagged.",
    ].map((bubble) => renderForPlatform(bubble, "telegram"));

    it("when the rewrite ends with a kept boundary", async () => {
      const { bubbles } = await deliver("telegram", [
        ...DRAFT,
        DISCARDED,
        ...REWRITE,
        KEPT,
      ]);

      // The draft's later bubbles were deleted and its first overwritten in
      // place: the rewrite is all that is left, once.
      expect(bubbles).toEqual(REWRITE_BUBBLES);
    });

    it("when the stream ends without a boundary", async () => {
      const { bubbles } = await deliver("telegram", [
        ...DRAFT,
        DISCARDED,
        ...REWRITE,
      ]);

      expect(bubbles).toEqual(REWRITE_BUBBLES);
    });
  });

  describe("a kept boundary delivers exactly what the stream end would", () => {
    const PARAGRAPHS =
      "First paragraph, long enough to stand on its own as a bubble.\n\n" +
      "Second paragraph, also long enough to stand on its own here.\n\n" +
      "Third paragraph, which is likewise long enough to be a bubble.";
    const PARAGRAPH_BUBBLES = [renderForPlatform(PARAGRAPHS, "telegram")];

    it("delivers a multi-paragraph reply with no sentinel as one bubble at the boundary", async () => {
      const { bubbles } = await deliver("telegram", [PARAGRAPHS, KEPT]);
      expect(bubbles).toEqual(PARAGRAPH_BUBBLES);
    });

    it("delivers the same one bubble when no boundary ever arrives", async () => {
      const { bubbles } = await deliver("telegram", [PARAGRAPHS]);
      expect(bubbles).toEqual(PARAGRAPH_BUBBLES);
    });

    it("splits a sentinel reply into the same bubbles at the boundary", async () => {
      const { bubbles } = await deliver("telegram", [
        GREETING,
        BREAK,
        CHECKED,
        BREAK,
        ANSWER,
        KEPT,
      ]);

      expect(bubbles).toEqual([
        renderForPlatform(GREETING, "telegram"),
        renderForPlatform(CHECKED, "telegram"),
        renderForPlatform(ANSWER, "telegram"),
      ]);
    });
  });

  it("caps the live preview at the platform limit, then delivers the overflow", async () => {
    // The preview holds a whole in-flight message, so it can outgrow the 4096-char
    // limit before the boundary splits it; an oversized edit is rejected outright
    // (freezing the bubble), so the preview is capped and overflow goes out at the boundary.
    const text = body("Alpha", 200);
    const { bubbles, writes } = await deliver("telegram", [text, KEPT]);

    for (const write of writes) {
      expect(write.length).toBeLessThanOrEqual(PLATFORM_LIMITS.telegram);
    }
    expect(bubbles.length).toBeGreaterThan(1);
    expect(words(bubbles.join(" "))).toBe(words(text));
  });

  it("never truncates, on any platform", async () => {
    for (const platform of [
      "telegram",
      "slack",
      "discord",
      "whatsapp",
      "imessage",
    ] as PlatformName[]) {
      const { writes } = await deliver(platform, [body("Alpha", 200), BREAK]);
      expect(writes.join(" ")).not.toContain("(truncated)");
    }
  });
});

describe("a stream that fails before it starts", () => {
  /** The API's real 429 body when the day's AI-usage budget is spent. */
  const RATE_LIMITED = Object.assign(
    new Error("Request failed with status code 429"),
    {
      response: {
        status: 429,
        data: {
          code: "rate_limit_exceeded",
          feature: "chat_messages",
          message:
            "You've used today's AI usage allowance. Upgrade to Pro for higher limits.",
          plan_required: "pro",
          current_plan: "free",
        },
      },
    },
  );

  it("tells the user once, not twice", async () => {
    // `streamChat` reports a non-retryable failure via `onError` AND rethrows, and
    // the streamer's outer catch reported it again — every rate limit/dead backend
    // arrived as two identical messages.
    const { errors } = await deliver("telegram", [], {
      failStream: RATE_LIMITED,
    });

    expect(errors).toHaveLength(1);
  });

  it("shows the server's own 429 copy, not the generic throttle line", async () => {
    // "You're sending messages too fast" is the wrong thing to tell someone who
    // is out of allowance: waiting does not fix it, upgrading does.
    const { errors } = await deliver("telegram", [], {
      failStream: RATE_LIMITED,
    });

    expect(errors[0]).toContain("today's AI usage allowance");
    expect(errors[0]).toContain("Upgrade to Pro");
    expect(errors[0]).not.toContain("too fast");
  });
});

describe("a rate-limit notice", () => {
  const NOTICE = "You've reached your chat limit. Please try again later.";

  it("is posted as its own message, not folded into the reply", async () => {
    const { bubbles } = await deliver("telegram", [
      "here's what I found",
      { notice: NOTICE },
      " and that's all of it.",
    ]);

    expect(bubbles).toContain(NOTICE);
    expect(bubbles.filter((b) => b.includes(NOTICE))).toHaveLength(1);
    expect(
      bubbles.find((b) => b.includes("here's what I found")),
    ).not.toContain(NOTICE);
  });

  it("survives the assistant message it arrived during being retracted", async () => {
    // The bug this frame exists for: the notice used to ride the stream as
    // reply text, so a discarded message took it with it — the user hit a wall
    // and was told nothing.
    const { bubbles } = await deliver("telegram", [
      "let me get that set up",
      { notice: NOTICE },
      DISCARDED,
      "all set.",
    ]);

    expect(bubbles).toContain(NOTICE);
    expect(bubbles).toContain("all set.");
    // The reply landed in its own message rather than overwriting the notice.
    expect(bubbles.indexOf("all set.")).toBeGreaterThan(
      bubbles.indexOf(NOTICE),
    );
  });
});

describe("what the user sees while a multi-bubble reply streams", () => {
  /** The throttle's interval and a little: long enough for one more live preview. */
  const gapFor = (platform: PlatformName) => ({
    waitMs: STREAMING_DEFAULTS[platform].editIntervalMs + 100,
  });

  it.each<PlatformName>(["telegram", "slack"])(
    "%s shows each bubble as its own message from its first words, and nothing vanishes",
    async (platform) => {
      const { bubbles, frames } = await deliver(platform, [
        GREETING,
        BREAK,
        "I checked your calendar",
        gapFor(platform),
        " for the whole of next week.",
        BREAK,
        ANSWER,
        gapFor(platform),
        KEPT,
      ]);

      expect(bubbles).toEqual(
        [GREETING, CHECKED, ANSWER].map((b) => renderForPlatform(b, platform)),
      );
      // The second bubble was on screen as a message of its own while it streamed.
      expect(frames).toContainEqual([
        renderForPlatform(GREETING, platform),
        renderForPlatform("I checked your calendar", platform),
      ]);
      expectNothingVanishes(frames);
    },
    10_000,
  );

  it("a retracted preamble's later bubbles are deleted, its first replaced in place", async () => {
    const { bubbles, frames } = await deliver("telegram", [
      "Sure thing, give me a second here.",
      BREAK,
      "Let me pull up your calendar",
      gapFor("telegram"),
      DISCARDED,
      ANSWER,
      KEPT,
    ]);

    expect(frames.some((frame) => frame.length === 2)).toBe(true);
    expect(bubbles).toEqual([renderForPlatform(ANSWER, "telegram")]);
  }, 10_000);

  it.each<PlatformName>(["discord", "whatsapp"])(
    "%s sends the bubbles in order with a pause between them",
    async (platform) => {
      const { bubbles, times } = await deliver(
        platform,
        [GREETING, BREAK, CHECKED, BREAK, ANSWER, KEPT],
        { editable: platform !== "whatsapp" },
      );

      expect(bubbles).toEqual(
        [GREETING, CHECKED, ANSWER].map((b) => renderForPlatform(b, platform)),
      );
      for (const [i, at] of times.slice(1).entries()) {
        expect(at - (times[i] ?? 0)).toBeGreaterThanOrEqual(
          BUBBLE_PAUSE_MS - 20,
        );
      }
    },
    10_000,
  );
});

describe("a stream that fails after bubbles were shown", () => {
  it("posts the error below them instead of overwriting one", async () => {
    const { bubbles, errors } = await deliver("telegram", [
      GREETING,
      BREAK,
      CHECKED,
      KEPT,
      { fail: "socket hang up" },
    ]);

    expect(errors).toEqual([]);
    expect(bubbles.slice(0, 2)).toEqual(
      [GREETING, CHECKED].map((b) => renderForPlatform(b, "telegram")),
    );
    expect(bubbles).toHaveLength(3);
  });
});
