/**
 * The outbound reaction path in `BaseBotAdapter`: one native attempt through
 * the adapter's `reactToMessage`, and the text fallback when it is refused.
 */

import { BOT_EVENTS } from "@gaia/shared/analytics";
import { BaseBotAdapter } from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";

const REACTION = { target_platform_message_id: "msg-7", emoji: "👍" };

/** Concrete adapter whose platform calls are spies. */
class TestAdapter extends BaseBotAdapter {
  readonly platform = "telegram" as const;
  protected readonly defaultServerPort = 3202;
  readonly sent =
    vi.fn<(id: string, text: string, isChannel: boolean) => Promise<void>>();

  protected async initialize(): Promise<void> {
    /* no platform client under test */
  }
  protected async registerCommands(): Promise<void> {
    /* no commands under test */
  }
  protected async registerEvents(): Promise<void> {
    /* no events under test */
  }
  protected async start(): Promise<void> {
    /* nothing to connect */
  }
  protected async stop(): Promise<void> {
    /* nothing to disconnect */
  }
  protected override async deliverOutbound(
    destinationId: string,
    text: string,
    isChannel: boolean,
  ): Promise<void> {
    await this.sent(destinationId, text, isChannel);
  }
}

/** A platform whose native reaction call resolves to `attached`. */
class ReactingAdapter extends TestAdapter {
  readonly react =
    vi.fn<
      (
        id: string,
        messageId: string,
        emoji: string,
        isChannel: boolean,
      ) => Promise<boolean>
    >();
  constructor(attached: boolean) {
    super();
    this.react.mockResolvedValue(attached);
  }
  protected override reactToMessage(
    destinationId: string,
    platformMessageId: string,
    emoji: string,
    isChannel: boolean,
  ): Promise<boolean> {
    return this.react(destinationId, platformMessageId, emoji, isChannel);
  }
}

async function deliver(adapter: TestAdapter) {
  const capture = vi.fn();
  Object.assign(adapter, {
    gaia: { checkAuthStatus: vi.fn(async () => ({ authenticated: false })) },
    analytics: { capture, alias: vi.fn() },
  });
  await (
    adapter as unknown as {
      deliverOutboundReaction: (
        id: string,
        reaction: typeof REACTION,
        isChannel: boolean,
      ) => Promise<void>;
    }
  ).deliverOutboundReaction("chat-1", REACTION, true);
  return capture;
}

describe("BaseBotAdapter outbound reaction", () => {
  it("attaches natively and sends no text", async () => {
    const adapter = new ReactingAdapter(true);

    const capture = await deliver(adapter);

    expect(adapter.react).toHaveBeenCalledWith("chat-1", "msg-7", "👍", true);
    expect(adapter.sent).not.toHaveBeenCalled();
    expect(capture).toHaveBeenCalledWith(
      "telegram:chat-1",
      BOT_EVENTS.REACTION_DELIVERED,
      { success: true, delivery: "native" },
    );
  });

  it("sends the emoji as text when the platform refuses the reaction", async () => {
    const adapter = new ReactingAdapter(false);

    const capture = await deliver(adapter);

    expect(adapter.sent).toHaveBeenCalledWith("chat-1", "👍", true);
    expect(capture).toHaveBeenCalledWith(
      "telegram:chat-1",
      BOT_EVENTS.REACTION_DELIVERED,
      { success: true, delivery: "fallback_text" },
    );
  });

  it("sends the emoji as text on a platform with no reaction API", async () => {
    const adapter = new TestAdapter();

    await deliver(adapter);

    expect(adapter.sent).toHaveBeenCalledWith("chat-1", "👍", true);
  });
});
