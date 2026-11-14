/**
 * A restarted bot resumes following the conversations the server lists as
 * still answering: a result that lands after the restart is delivered once,
 * and a reply delivered before the restart is not sent again.
 *
 * The follower, its registry and the delivery machine are real; the GAIA
 * client is a fake log that replays entries after the requested seq the way
 * the events route does, and the platform is a recorder.
 */
import {
  type ActiveBotConversation,
  BaseBotAdapter,
  type ConversationSurface,
  REACTION_OUTCOME,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import {
  replyItem,
  screenFrame,
  stateFrame,
  userItemWith,
  workItem,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type {
  ConversationFrame,
  ScreenItem,
} from "../../../../../libs/shared/ts/src/conversation/types";

/** The conversation's screen: a request already answered "On it.", then the work's late result. */
const SCREEN: ScreenItem[] = [
  userItemWith("u1", 1, { surface: "whatsapp", platform_message_id: "11" }),
  replyItem("r1", 2, "On it.", "answered"),
  workItem("t1", 4, "done"),
  replyItem("t1", 6, "Your flight is booked.", "answered"),
];

/** Opens on the screen, then the conversation's state, as the events route does. */
async function* replay(): AsyncGenerator<ConversationFrame> {
  yield screenFrame(SCREEN);
  yield stateFrame(7, "idle");
}

class RestartedAdapter extends BaseBotAdapter {
  readonly platform = "whatsapp" as const;
  protected readonly defaultServerPort = 3203;
  readonly sent: string[] = [];
  readonly targets: ActiveBotConversation[] = [];

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
  protected async resumeSurface(
    target: ActiveBotConversation,
  ): Promise<ConversationSurface> {
    this.targets.push(target);
    return {
      send: async (text) => {
        this.sent.push(text);
        return { edit: async () => undefined };
      },
      react: async () => REACTION_OUTCOME.ATTACHED,
      startTyping: () => () => undefined,
    };
  }

  /** Boot's resume step, the one this test drives. */
  resume(): Promise<void> {
    return this.resumeFollows();
  }
}

function restarted(active: ActiveBotConversation[]) {
  const adapter = new RestartedAdapter();
  const opened = vi.fn(replay);
  const listActiveConversations = vi.fn(async () => active);
  Object.assign(adapter, {
    gaia: {
      listActiveConversations,
      conversationEvents: opened,
    },
  });
  return { adapter, opened, listActiveConversations };
}

const target = (afterSeq: number): ActiveBotConversation => ({
  conversation_id: "c1",
  platform_user_id: "15551234",
  channel_id: null,
  is_dm: true,
  after_seq: afterSeq,
  partial_reply: null,
});

describe("a bot restarted while work ran", () => {
  it("delivers the result that landed after the restart, once", async () => {
    const { adapter, opened, listActiveConversations } = restarted([target(3)]);

    await adapter.resume();
    await adapter.conversationsIdle();

    expect(listActiveConversations).toHaveBeenCalledWith("whatsapp");
    expect(adapter.targets).toEqual([target(3)]);
    expect(opened).toHaveBeenCalledTimes(1);
    expect(adapter.sent).toEqual(["Your flight is booked."]);
  });

  it("sends nothing again when the reply was delivered before the restart", async () => {
    const { adapter, opened } = restarted([target(7)]);

    await adapter.resume();
    await adapter.conversationsIdle();

    expect(opened).toHaveBeenCalledTimes(1);
    expect(adapter.sent).toEqual([]);
  });
});
