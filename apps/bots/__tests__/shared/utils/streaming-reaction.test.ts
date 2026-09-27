/**
 * A live turn answered with a reaction, through the real streamer end to end.
 *
 * Both halves run for real — `streamChat` parsing the SSE body and
 * `handleStreamingChat` rendering it — with only the axios transport and the
 * platform send/edit/react callbacks faked. The turn used to arrive as a
 * separate text message holding the bare emoji on every platform.
 */
import { Readable } from "node:stream";
import { BOT_EVENTS } from "@gaia/shared/analytics";
import {
  GaiaClient,
  handleStreamingChat,
  type PlatformName,
  STREAMING_DEFAULTS,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import type { AnalyticsContext } from "../../../../../libs/shared/ts/src/analytics";

const PLACEHOLDER = "Thinking...";

function frames(...payloads: object[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

const REACTION_TURN = frames(
  { text: "<EMOJI>😅</EMOJI>" },
  { message_boundary: { message_id: "m1", discarded: false } },
  { emoji_ack: { emoji: "😅", reacts_to_message_id: "u1" } },
  { done: true, conversation_id: "c1" },
);

/** A real GaiaClient whose HTTP transport replays one scripted SSE body. */
function gaiaReplaying(sseBody: string): GaiaClient {
  const gaia = new GaiaClient("http://gaia.test", "key", "http://web.test");
  (gaia as unknown as { client: unknown }).client = {
    post: vi.fn(async () => ({ data: Readable.from([sseBody]) })),
  };
  return gaia;
}

interface Screen {
  /** Messages left on screen, in order; the placeholder counts until removed. */
  messages: string[];
  errors: string[];
  reactions: string[];
}

/**
 * Streams one turn the way the Telegram adapter wires it: a "Thinking..."
 * placeholder the reply edits in place, which a successful reaction removes.
 */
async function runTurn(
  platform: PlatformName,
  sseBody: string,
  react?: (emoji: string) => Promise<boolean>,
  analytics?: AnalyticsContext,
): Promise<Screen> {
  const screen: Screen = { messages: [PLACEHOLDER], errors: [], reactions: [] };
  let live = 0;

  await handleStreamingChat(
    gaiaReplaying(sseBody),
    {
      message: "that fixed it, thanks",
      platform,
      platformUserId: "u1",
      channelId: "c1",
      platformMessageId: "inbound-1",
    },
    async (text) => {
      screen.messages[live] = text;
    },
    async (text) => {
      screen.messages.push(text);
      const index = screen.messages.length - 1;
      live = index;
      return async (updated) => {
        screen.messages[index] = updated;
      };
    },
    async () => {
      throw new Error("auth path is not exercised here");
    },
    async (formattedError) => {
      screen.errors.push(formattedError);
    },
    STREAMING_DEFAULTS[platform],
    analytics,
    react &&
      (async (emoji) => {
        const reacted = await react(emoji);
        if (reacted) {
          screen.reactions.push(emoji);
          screen.messages.splice(screen.messages.indexOf(PLACEHOLDER), 1);
        }
        return reacted;
      }),
  );
  return screen;
}

describe("a live turn answered with a reaction", () => {
  it.each<PlatformName>(["telegram", "slack", "discord", "whatsapp"])(
    "%s attaches the emoji and posts nothing",
    async (platform) => {
      const react = vi.fn(async () => true);

      const screen = await runTurn(platform, REACTION_TURN, react);

      expect(react).toHaveBeenCalledExactlyOnceWith("😅");
      expect(screen.reactions).toEqual(["😅"]);
      expect(screen.messages).toEqual([]);
      expect(screen.errors).toEqual([]);
    },
  );

  it.each<PlatformName>(["telegram", "whatsapp"])(
    "%s sends the emoji as text when the platform refuses the reaction",
    async (platform) => {
      const screen = await runTurn(platform, REACTION_TURN, async () => false);

      expect(screen.messages).toEqual(["😅"]);
      expect(screen.reactions).toEqual([]);
    },
  );

  it("sends the emoji as text when the call site has nothing to react to", async () => {
    const screen = await runTurn("telegram", REACTION_TURN);

    expect(screen.messages).toEqual(["😅"]);
  });

  it("counts a reaction as the reply when the stream closes without a done frame", async () => {
    const screen = await runTurn(
      "whatsapp",
      frames(
        { text: "<EMOJI>😅</EMOJI>" },
        { emoji_ack: { emoji: "😅", reacts_to_message_id: "u1" } },
      ),
      async () => true,
    );

    expect(screen.errors).toEqual([]);
    expect(screen.messages).toEqual([]);
  });

  it.each([
    [true, "native"],
    [false, "fallback_text"],
  ])(
    "records the delivery when the reaction attaches: %s",
    async (attached, delivery) => {
      const capture = vi.fn();
      const analytics = {
        client: { capture },
        distinctId: "gaia-user-1",
      } as unknown as AnalyticsContext;

      await runTurn("telegram", REACTION_TURN, async () => attached, analytics);

      expect(capture).toHaveBeenCalledWith(
        "gaia-user-1",
        BOT_EVENTS.REACTION_DELIVERED,
        { success: true, delivery },
      );
    },
  );
});
