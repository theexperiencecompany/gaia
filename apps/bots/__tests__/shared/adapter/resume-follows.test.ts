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
  entryFrame,
  entryUpdatedFrame,
  reply,
  replySettled,
  stateFrame,
  userMessage,
  workFinished,
  workStarted,
} from "../../../../../libs/shared/ts/src/conversation/testing";
import type {
  ConversationFrame,
  ConversationStreamEvent,
} from "../../../../../libs/shared/ts/src/conversation/types";

/** The conversation's log: a request already answered "On it.", then the work's late result. */
const LOG: ConversationFrame[] = [
  entryFrame(1, {
    ...userMessage("u1"),
    surface: "whatsapp",
    platform_message_id: "11",
  }),
  entryFrame(2, reply("r1", "a-r1", "On it.", 1)),
  entryFrame(3, replySettled("r1", ["u1"], 1)),
  entryFrame(4, workStarted("t1", 1)),
  entryFrame(5, workFinished("t1")),
  entryFrame(6, reply("t1", "a-t1")),
  entryUpdatedFrame(6, reply("t1", "a-t1", "Your flight is booked.", 1)),
  entryFrame(7, replySettled("t1", ["u1"], 5)),
];

const seqOf = (frame: ConversationFrame): number =>
  frame.kind === "entry" || frame.kind === "entry_updated" ? frame.seq : 0;

/** Replays the log after a seq, then the conversation's state, as the events route does. */
async function* replay(
  log: ConversationFrame[],
  after: string,
): AsyncGenerator<ConversationStreamEvent> {
  for (const frame of log) {
    if (seqOf(frame) > Number(after)) yield { streamId: null, frame };
  }
  yield { streamId: "9-0", frame: stateFrame(log.length, "idle") };
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
  const cursors: string[] = [];
  const listActiveConversations = vi.fn(async () => active);
  Object.assign(adapter, {
    gaia: {
      listActiveConversations,
      conversationEvents: (
        _ctx: unknown,
        _conversationId: string,
        after: string,
      ) => {
        cursors.push(after);
        return replay(LOG, after);
      },
    },
  });
  return { adapter, cursors, listActiveConversations };
}

const target = (afterSeq: number): ActiveBotConversation => ({
  conversation_id: "c1",
  platform_user_id: "15551234",
  channel_id: null,
  is_dm: true,
  after_seq: afterSeq,
});

describe("a bot restarted while work ran", () => {
  it("delivers the result that landed after the restart, once", async () => {
    const { adapter, cursors, listActiveConversations } = restarted([
      target(3),
    ]);

    await adapter.resume();
    await adapter.conversationsIdle();

    expect(listActiveConversations).toHaveBeenCalledWith("whatsapp");
    expect(adapter.targets).toEqual([target(3)]);
    expect(cursors).toEqual(["3"]);
    expect(adapter.sent).toEqual(["Your flight is booked."]);
  });

  it("sends nothing again when the reply was delivered before the restart", async () => {
    const { adapter, cursors } = restarted([target(7)]);

    await adapter.resume();
    await adapter.conversationsIdle();

    expect(cursors).toEqual(["7"]);
    expect(adapter.sent).toEqual([]);
  });
});
