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
  neverReopened,
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
  /** Errors the platform throws for the next sends, in order. */
  readonly refusals: Error[] = [];
  sendAttempts = 0;
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
        this.sendAttempts += 1;
        const refusal = this.refusals.shift();
        if (refusal) throw refusal;
        this.sent.push(text);
        return { id: `m${this.sent.length}`, edit: async () => undefined };
      },
      reopen: neverReopened("telegram"),
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
  const recordDelivered = vi.fn(async () => ({ recorded: true }));
  Object.assign(adapter, {
    gaia: {
      listActiveConversations,
      conversationEvents: opened,
      recordDelivered,
    },
  });
  return { adapter, opened, listActiveConversations, recordDelivered };
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

/** What axios throws when nothing listens on the API's port yet. */
const refused = () =>
  Object.assign(new Error("connect ECONNREFUSED 127.0.0.1:8000"), {
    code: "ECONNREFUSED",
  });

describe("a bot that boots before the API listens", () => {
  it("asks again with backoff until the API answers, then delivers", async () => {
    const { adapter, listActiveConversations } = restarted([target(3)]);
    listActiveConversations
      .mockRejectedValueOnce(refused())
      .mockRejectedValueOnce(refused());
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const resumed = adapter.resume();
      await vi.advanceTimersByTimeAsync(10_000);
      await resumed;
    } finally {
      vi.useRealTimers();
    }
    await adapter.conversationsIdle();

    expect(listActiveConversations).toHaveBeenCalledTimes(3);
    expect(adapter.sent).toEqual(["Your flight is booked."]);
  });

  it("does not ask again when the API refuses the bot for good", async () => {
    const { adapter, listActiveConversations } = restarted([target(3)]);
    listActiveConversations.mockRejectedValueOnce(
      Object.assign(new Error("Request failed with status code 401"), {
        response: { status: 401, data: { code: "BOT_API_KEY_INVALID" } },
      }),
    );
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const resumed = adapter.resume();
      await vi.advanceTimersByTimeAsync(10_000);
      await resumed;
    } finally {
      vi.useRealTimers();
    }

    expect(listActiveConversations).toHaveBeenCalledTimes(1);
    expect(adapter.sent).toEqual([]);
  });

  it("stops waiting for the API on shutdown", async () => {
    const { adapter, listActiveConversations } = restarted([target(3)]);
    listActiveConversations.mockRejectedValue(refused());
    const resumed = adapter.resume();
    await vi.waitFor(() =>
      expect(listActiveConversations).toHaveBeenCalledTimes(1),
    );

    await adapter.shutdown("SIGTERM");
    await resumed;

    expect(listActiveConversations).toHaveBeenCalledTimes(1);
  });
});

/** grammY's GrammyError: Telegram's status in error_code, its reason in description. */
const grammyError = (
  status: number,
  description: string,
  parameters?: { retry_after: number },
) =>
  Object.assign(new Error(`(${status}: ${description})`), {
    name: "GrammyError",
    error_code: status,
    description,
    parameters,
  });

describe("a platform send during a follow", () => {
  it("is sent again after the platform's retry_after on a rate limit, and the replies land in order", async () => {
    const { adapter } = restarted([target(1)]);
    adapter.refusals.push(
      grammyError(429, "Too Many Requests: retry after 0", { retry_after: 0 }),
    );

    await adapter.resume();
    await adapter.conversationsIdle();

    expect(adapter.sent).toEqual(["On it.", "Your flight is booked."]);
  });

  it("stops after a send whose cursor the server would not keep, so a restart repeats nothing past the kept cursor", async () => {
    const { adapter, recordDelivered } = restarted([target(1)]);
    recordDelivered.mockRejectedValue(
      Object.assign(new Error("Request failed with status code 422"), {
        response: { status: 422, data: {} },
      }),
    );

    await adapter.resume();
    await adapter.conversationsIdle();

    expect(recordDelivered).toHaveBeenCalledTimes(1);
    expect(adapter.sent).toEqual([]);
  });

  it("is not sent again when the chat is gone, and that follow ends", async () => {
    const { adapter } = restarted([target(1)]);
    adapter.refusals.push(grammyError(400, "Bad Request: chat not found"));

    await adapter.resume();
    await adapter.conversationsIdle();

    expect(adapter.sendAttempts).toBe(1);
    expect(adapter.sent).toEqual([]);
  });
});
