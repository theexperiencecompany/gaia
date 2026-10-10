/**
 * A live turn answered with a reaction, through the real streamer end to end.
 *
 * Both halves run for real — `streamChat` parsing the SSE body and
 * `handleStreamingChat` rendering it — with only the axios transport and the
 * platform send/edit/react callbacks faked. The turn used to arrive as a
 * separate text message holding the bare emoji on every platform.
 */
import { Readable } from "node:stream";
import { parseUserId } from "@gaia/shared/analytics";
import {
  GaiaClient,
  handleStreamingChat,
  type PlatformName,
  REACTION_OUTCOME,
  type ReactionOutcome,
  STREAMING_DEFAULTS,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import type { AnalyticsContext } from "../../../../../libs/shared/ts/src/analytics";

const PLACEHOLDER = "Thinking...";
const USER_ID = parseUserId("6812f0b3c9a14e2b7d5a91cc");

function frames(...payloads: object[]): string {
  return payloads.map((p) => `data: ${JSON.stringify(p)}\n\n`).join("");
}

const REACTION_TURN = frames(
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
  react?: (emoji: string) => Promise<ReactionOutcome>,
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
        const outcome = await react(emoji);
        if (outcome === REACTION_OUTCOME.ATTACHED) {
          screen.reactions.push(emoji);
          screen.messages.splice(screen.messages.indexOf(PLACEHOLDER), 1);
        }
        return outcome;
      }),
  );
  return screen;
}

describe("a live turn answered with a reaction", () => {
  it.each<PlatformName>(["telegram", "slack", "discord", "whatsapp"])(
    "%s attaches the emoji and posts nothing",
    async (platform) => {
      const react = vi.fn(async () => REACTION_OUTCOME.ATTACHED);

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
      const screen = await runTurn(
        platform,
        REACTION_TURN,
        async () => REACTION_OUTCOME.ATTACH_FAILED,
      );

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
      frames({ emoji_ack: { emoji: "😅", reacts_to_message_id: "u1" } }),
      async () => REACTION_OUTCOME.ATTACHED,
    );

    expect(screen.errors).toEqual([]);
    expect(screen.messages).toEqual([]);
  });

  it.each<[ReactionOutcome, object]>([
    [REACTION_OUTCOME.ATTACHED, { delivery: "native" }],
    [
      REACTION_OUTCOME.ATTACH_FAILED,
      { delivery: "fallback_text", reason: "attach_failed" },
    ],
    [
      REACTION_OUTCOME.UNMAPPED_EMOJI,
      { delivery: "fallback_text", reason: "unmapped_emoji" },
    ],
  ])("records a live reaction that ended %s", async (outcome, expected) => {
    const capture = vi.fn();

    await runTurn(
      "telegram",
      REACTION_TURN,
      async () => outcome,
      analyticsCapturingTo(capture),
    );

    expect(reactionCaptures(capture)).toStrictEqual([
      { success: true, surface: "live", ...expected },
    ]);
  });

  it("records no_target when the call site has nothing to react to", async () => {
    const capture = vi.fn();

    await runTurn(
      "telegram",
      REACTION_TURN,
      undefined,
      analyticsCapturingTo(capture),
    );

    expect(reactionCaptures(capture)).toStrictEqual([
      {
        success: true,
        surface: "live",
        delivery: "fallback_text",
        reason: "no_target",
      },
    ]);
  });
});

/** The properties of every reaction event, captured for the turn's user. */
function reactionCaptures(capture: ReturnType<typeof vi.fn>): unknown[] {
  return capture.mock.calls
    .filter(
      ([distinctId, event]) =>
        distinctId === USER_ID && event === "bot:reaction_delivered",
    )
    .map(([, , properties]) => properties);
}

function analyticsCapturingTo(
  capture: ReturnType<typeof vi.fn>,
): AnalyticsContext {
  return {
    client: { capture },
    distinctId: USER_ID,
  } as unknown as AnalyticsContext;
}
