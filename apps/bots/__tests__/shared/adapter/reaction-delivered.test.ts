/**
 * A reaction the conversation follower places through the adapter's surface is
 * captured as bot:reaction_delivered once the platform accepted it, and not otherwise.
 *
 * The follower and the adapter's surface wrapping are real; the GAIA client is a
 * fake log, the platform a scripted outcome, and analytics a recorder.
 */
import {
  type ActiveBotConversation,
  BaseBotAdapter,
  type ConversationSurface,
  REACTION_OUTCOME,
  type ReactionOutcome,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import {
  screenFrame,
  stateFrame,
  userItemWith,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type { ConversationFrame } from "../../../../../libs/shared/ts/src/conversation/types";

async function* replay(): AsyncGenerator<ConversationFrame> {
  yield screenFrame([
    userItemWith("u1", 1, {
      text: "hi",
      reaction: { emoji: "👍", by: "jev" },
      surface: "whatsapp",
      platform_message_id: "11",
    }),
  ]);
  yield stateFrame(1, "idle");
}

class ReactingAdapter extends BaseBotAdapter {
  readonly platform = "whatsapp" as const;
  protected readonly defaultServerPort = 3204;
  outcome: ReactionOutcome = REACTION_OUTCOME.ATTACHED;

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
  protected async sendOutboundFile(): Promise<void> {
    /* no file delivery under test */
  }
  protected async deliverOutbound(): Promise<void> {
    /* no outbound queue under test */
  }
  protected async resumeSurface(): Promise<ConversationSurface> {
    return {
      send: async () => ({ edit: async () => undefined }),
      react: async () => this.outcome,
      startTyping: () => () => undefined,
    };
  }

  resume(): Promise<void> {
    return this.resumeFollows();
  }
}

const target: ActiveBotConversation = {
  conversation_id: "c1",
  platform_user_id: "15551234",
  channel_id: null,
  is_dm: true,
  after_seq: 0,
  partial_reply: null,
};

async function followReaction(outcome: ReactionOutcome) {
  const adapter = new ReactingAdapter();
  adapter.outcome = outcome;
  const capture = vi.fn();
  Object.assign(adapter, {
    analytics: { capture, alias: vi.fn() },
    gaia: {
      listActiveConversations: async () => [target],
      checkAuthStatus: async () => ({ user_id: null }),
      conversationEvents: () => replay(),
    },
  });
  await adapter.resume();
  await adapter.conversationsIdle();
  return capture;
}

describe("bot:reaction_delivered", () => {
  it("is captured once for a reaction the platform attached", async () => {
    const capture = await followReaction(REACTION_OUTCOME.ATTACHED);

    expect(capture).toHaveBeenCalledTimes(1);
    expect(capture).toHaveBeenCalledWith(
      "whatsapp:15551234",
      "bot:reaction_delivered",
      { success: true, surface: "live", delivery: "native" },
    );
  });

  it("is not captured when the platform call failed", async () => {
    const capture = await followReaction(REACTION_OUTCOME.ATTACH_FAILED);

    expect(capture).not.toHaveBeenCalled();
  });
});
