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
  type GaiaClient,
  handleStreamingChat,
  PLATFORM_LIMITS,
  type PlatformName,
  renderForPlatform,
  STREAMING_DEFAULTS,
} from "@gaia/shared";
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
function streamingGaia(chunks: string[], approvalAfter?: number): GaiaClient {
  const full = chunks.join("");
  return {
    chatStream: async (
      _request: unknown,
      onChunk: (text: string) => void | Promise<void>,
      onDone: (
        fullText: string,
        conversationId: string,
      ) => void | Promise<void>,
      _onError: unknown,
      onApproval?: (data: ApprovalRequestData) => void | Promise<void>,
    ) => {
      for (const [i, chunk] of chunks.entries()) {
        await onChunk(chunk);
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
          } as ApprovalRequestData);
        }
      }
      await onDone(full, "conv-test");
      return full;
    },
    createLinkToken: async () => ({ authUrl: "https://gaia.test/link" }),
  } as unknown as GaiaClient;
}

interface Delivered {
  /** Final text of every message the platform ended up holding, in order. */
  bubbles: string[];
  /** Every distinct text the platform was ever asked to display. */
  writes: string[];
}

/**
 * Runs one streamed turn against a platform, emulating that platform's real
 * edit semantics: editable platforms update the live message in place,
 * non-editable ones (WhatsApp, iMessage) turn every edit into a new message.
 */
async function deliver(
  platform: PlatformName,
  chunks: string[],
  {
    editable = true,
    approvalAfter,
  }: { editable?: boolean; approvalAfter?: number } = {},
): Promise<Delivered> {
  const bubbles: string[] = [];
  const writes: string[] = [];
  let current = -1;

  const editMessage = async (text: string): Promise<void> => {
    writes.push(text);
    if (current === -1 || !editable) {
      bubbles.push(text);
      current = bubbles.length - 1;
      return;
    }
    bubbles[current] = text;
  };

  const sendNewMessage = async (text: string) => {
    writes.push(text);
    bubbles.push(text);
    const index = bubbles.length - 1;
    current = index;
    return async (updated: string): Promise<void> => {
      writes.push(updated);
      if (editable) {
        bubbles[index] = updated;
        return;
      }
      bubbles.push(updated);
    };
  };

  await handleStreamingChat(
    streamingGaia(chunks, approvalAfter),
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
      throw new Error(`unexpected stream error: ${formattedError}`);
    },
    STREAMING_DEFAULTS[platform],
  );

  return { bubbles, writes };
}

/** Word count, so text is compared by content rather than exact whitespace. */
function words(text: string): number {
  return text.split(/\s+/).filter(Boolean).length;
}

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
          "Hey there.",
          BREAK,
          "I checked your calendar.",
          BREAK,
          "You are free at 3pm.",
        ]);

        expect(bubbles).toEqual([
          renderForPlatform("Hey there.", platform),
          renderForPlatform("I checked your calendar.", platform),
          renderForPlatform("You are free at 3pm.", platform),
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
    // The approval prompt is posted through the adapter's `sendNewMessage`,
    // which on editing platforms moves that adapter's live-edit cursor onto the
    // prompt. If the streamer keeps editing "the current message" afterwards it
    // writes the rest of the reply over the question the user still has to
    // answer.
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
      "Hey there.",
      "<NEW_LINE_BREAK>",
      "I checked your calendar.",
    ]);

    expect(bubbles).toEqual([
      renderForPlatform("Hey there.", "telegram"),
      renderForPlatform("I checked your calendar.", "telegram"),
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
