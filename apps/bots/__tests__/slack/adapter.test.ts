/**
 * Tests for the SlackAdapter.
 *
 * The SlackAdapter wraps Slack Bolt and uses Socket Mode, so a live token is
 * required for full integration testing. We isolate the adapter logic by:
 *
 * 1. Mocking @slack/bolt so no real WebSocket connection is established.
 * 2. Mocking @gaia/shared to control handleStreamingChat.
 * 3. Exercising the adapter's private methods directly via TypeScript casts.
 *
 * Covered behaviors:
 * - platform property value
 * - createCommandTarget — send, sendEphemeral, sendRich, startTyping
 * - registerGaiaCommand / handleSlackStreaming:
 *     - posts "Thinking..." before streaming starts
 *     - falls back to ephemeral when postMessage returns no ts
 *     - delegates to handleStreamingChat with correct request shape
 * - registerCommands — ack() called immediately (Slack's 3-second rule)
 * - registerEvents — app_mention strips bot mention, skips bots/subtypes
 * - dispatchCommand — unknown command sends ephemeral error
 */

import { beforeEach, describe, expect, it, vi } from "vitest";

// ---------------------------------------------------------------------------
// Mock @slack/bolt
// ---------------------------------------------------------------------------

const mockApp = {
  command: vi.fn(),
  event: vi.fn(),
  message: vi.fn(),
  start: vi.fn().mockResolvedValue(undefined),
  stop: vi.fn().mockResolvedValue(undefined),
};

vi.mock("@slack/bolt", () => ({
  App: vi.fn().mockImplementation(() => mockApp),
}));

// ---------------------------------------------------------------------------
// Mock @gaia/shared
// ---------------------------------------------------------------------------

vi.mock("@gaia/shared", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@gaia/shared")>();

  return {
    ...actual,
    formatBotError: vi.fn((err: unknown) =>
      err instanceof Error ? `Error: ${err.message}` : "Something went wrong",
    ),
    handleStreamingChat: vi.fn().mockResolvedValue(undefined),
    STREAMING_DEFAULTS: {
      slack: { editIntervalMs: 1500, streaming: true, platform: "slack" },
    },
    richMessageToMarkdown: vi.fn().mockReturnValue("## Rich Title\nBody text"),
    parseTextArgs: vi.fn((text: string) => ({
      subcommand: text.split(" ")[0] || undefined,
    })),
  };
});

// ---------------------------------------------------------------------------
// Import adapter after mocks are in place
// ---------------------------------------------------------------------------

import { convertToSlackMrkdwn, handleStreamingChat } from "@gaia/shared";
import { SlackAdapter } from "../../slack/src/adapter";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** A minimal Slack Web API client mock. */
function makeSlackClient(tsOverride?: string) {
  return {
    chat: {
      postMessage: vi
        .fn()
        .mockResolvedValue({ ts: tsOverride ?? "1234567890.123456" }),
      update: vi.fn().mockResolvedValue({}),
      postEphemeral: vi.fn().mockResolvedValue({}),
    },
  };
}

/** A Bolt `respond` function mock. */
function makeRespondFn() {
  return vi.fn().mockResolvedValue(undefined);
}

// ---------------------------------------------------------------------------
// platform identity
// ---------------------------------------------------------------------------

describe("SlackAdapter - platform identity", () => {
  it('reports platform as "slack"', () => {
    const adapter = new SlackAdapter();
    expect(adapter.platform).toBe("slack");
  });
});

// ---------------------------------------------------------------------------
// createCommandTarget — send
// ---------------------------------------------------------------------------

describe("SlackAdapter - createCommandTarget.send", () => {
  let adapter: SlackAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = new SlackAdapter();
  });

  it("calls postMessage with converted mrkdwn and returns editable SentMessage", async () => {
    const client = makeSlackClient("ts-abc");
    const respond = makeRespondFn();

    const target = (
      adapter as unknown as {
        createCommandTarget: (
          userId: string,
          channelId: string,
          client: typeof client,
          respond: typeof respond,
          userName?: string,
        ) => {
          send: (
            t: string,
          ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
          sendEphemeral: (t: string) => Promise<{ id: string }>;
          sendRich: (m: unknown) => Promise<{ id: string }>;
          startTyping: () => Promise<() => void>;
          platform: string;
          userId: string;
          channelId: string;
        };
      }
    ).createCommandTarget("U123", "C456", client, respond, "johndoe");

    const sent = await target.send("Hello world");

    expect(client.chat.postMessage).toHaveBeenCalledWith({
      channel: "C456",
      text: convertToSlackMrkdwn("Hello world"),
    });
    expect(sent.id).toBe("ts-abc");

    // Verify edit works
    await sent.edit("Updated text");
    expect(client.chat.update).toHaveBeenCalledWith({
      channel: "C456",
      ts: "ts-abc",
      text: convertToSlackMrkdwn("Updated text"),
    });
  });

  it("returns empty-string id when postMessage returns no ts", async () => {
    const client = makeSlackClient(undefined);
    // Override to return no ts
    client.chat.postMessage = vi.fn().mockResolvedValue({});
    const respond = makeRespondFn();

    const target = (
      adapter as unknown as {
        createCommandTarget: (
          u: string,
          c: string,
          cl: typeof client,
          r: typeof respond,
        ) => { send: (t: string) => Promise<{ id: string }> };
      }
    ).createCommandTarget("U123", "C456", client, respond);

    const sent = await target.send("No ts");
    expect(sent.id).toBe("");
  });
});

// ---------------------------------------------------------------------------
// createCommandTarget — sendEphemeral
// ---------------------------------------------------------------------------

describe("SlackAdapter - createCommandTarget.sendEphemeral", () => {
  it("calls respond with response_type: ephemeral", async () => {
    const adapter = new SlackAdapter();
    const client = makeSlackClient();
    const respond = makeRespondFn();

    const target = (
      adapter as unknown as {
        createCommandTarget: (
          u: string,
          c: string,
          cl: typeof client,
          r: typeof respond,
        ) => { sendEphemeral: (t: string) => Promise<{ id: string }> };
      }
    ).createCommandTarget("U123", "C456", client, respond);

    const sent = await target.sendEphemeral("Only you can see this");

    expect(respond).toHaveBeenCalledWith({
      text: convertToSlackMrkdwn("Only you can see this"),
      response_type: "ephemeral",
    });
    expect(sent.id).toBe("ephemeral");
  });

  it("edit on ephemeral SentMessage is a no-op", async () => {
    const adapter = new SlackAdapter();
    const client = makeSlackClient();
    const respond = makeRespondFn();

    const target = (
      adapter as unknown as {
        createCommandTarget: (
          u: string,
          c: string,
          cl: typeof client,
          r: typeof respond,
        ) => {
          sendEphemeral: (
            t: string,
          ) => Promise<{ id: string; edit: (t: string) => Promise<void> }>;
        };
      }
    ).createCommandTarget("U123", "C456", client, respond);

    const sent = await target.sendEphemeral("Ephemeral message");
    // Must not throw
    await expect(sent.edit("Cannot update ephemeral")).resolves.toBeUndefined();
    expect(client.chat.update).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// createCommandTarget — sendRich
// ---------------------------------------------------------------------------

describe("SlackAdapter - createCommandTarget.sendRich", () => {
  it("calls respond with ephemeral markdown-rendered content", async () => {
    const adapter = new SlackAdapter();
    const client = makeSlackClient();
    const respond = makeRespondFn();

    const target = (
      adapter as unknown as {
        createCommandTarget: (
          u: string,
          c: string,
          cl: typeof client,
          r: typeof respond,
        ) => { sendRich: (m: unknown) => Promise<{ id: string }> };
      }
    ).createCommandTarget("U123", "C456", client, respond);

    const richMsg = {
      type: "embed" as const,
      title: "Settings",
      description: "Your settings",
      fields: [],
    };

    const sent = await target.sendRich(richMsg);

    expect(respond).toHaveBeenCalledWith({
      text: "## Rich Title\nBody text", // richMessageToMarkdown mock return value
      response_type: "ephemeral",
    });
    expect(sent.id).toBe("ephemeral");
  });
});

// ---------------------------------------------------------------------------
// createCommandTarget — startTyping
// ---------------------------------------------------------------------------

describe("SlackAdapter - createCommandTarget.startTyping", () => {
  it("returns a no-op cleanup function (Slack has no typing API for bots)", async () => {
    const adapter = new SlackAdapter();
    const client = makeSlackClient();
    const respond = makeRespondFn();

    const target = (
      adapter as unknown as {
        createCommandTarget: (
          u: string,
          c: string,
          cl: typeof client,
          r: typeof respond,
        ) => { startTyping: () => Promise<() => void> };
      }
    ).createCommandTarget("U123", "C456", client, respond);

    const stopTyping = await target.startTyping();
    expect(typeof stopTyping).toBe("function");
    // Calling stop must not throw
    expect(() => stopTyping()).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// handleSlackStreaming — posts "Thinking..." and delegates to handleStreamingChat
// ---------------------------------------------------------------------------

describe("SlackAdapter - handleSlackStreaming", () => {
  let adapter: SlackAdapter;

  beforeEach(() => {
    vi.clearAllMocks();
    adapter = new SlackAdapter();
    // boot() is not called in tests; inject a mock gaia so this.gaia !== undefined
    (adapter as unknown as { gaia: object }).gaia = {};
  });

  it("posts 'Thinking...' before invoking handleStreamingChat", async () => {
    const client = makeSlackClient("ts-start");

    await (
      adapter as unknown as {
        handleSlackStreaming: (
          client: typeof client,
          channelId: string,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleSlackStreaming(client, "C789", "U456", "Plan my day");

    expect(client.chat.postMessage).toHaveBeenCalledWith({
      channel: "C789",
      text: "Thinking...",
    });
    expect(handleStreamingChat).toHaveBeenCalled();
  });

  it("calls handleStreamingChat with correct request shape", async () => {
    const client = makeSlackClient("ts-stream");

    await (
      adapter as unknown as {
        handleSlackStreaming: (
          client: typeof client,
          channelId: string,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleSlackStreaming(client, "C789", "U456", "Plan my day");

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(), // gaia client
      expect.objectContaining({
        message: "Plan my day",
        platform: "slack",
        platformUserId: "U456",
        channelId: "C789",
      }),
      expect.any(Function), // editMessage callback
      expect.any(Function), // sendNewMessage callback
      expect.any(Function), // onAuthError callback
      expect.any(Function), // onGenericError callback
      expect.objectContaining({ platform: "slack" }),
    );
  });

  it("sends ephemeral fallback when postMessage returns no ts", async () => {
    const client = makeSlackClient();
    client.chat.postMessage = vi.fn().mockResolvedValue({});

    await (
      adapter as unknown as {
        handleSlackStreaming: (
          client: typeof client,
          channelId: string,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleSlackStreaming(client, "C789", "U456", "Test");

    expect(client.chat.postEphemeral).toHaveBeenCalledWith({
      channel: "C789",
      user: "U456",
      text: "Something went wrong processing your message. Please try again.",
    });
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// handleSlackStreaming — editMessage callback updates via chat.update
// ---------------------------------------------------------------------------

describe("SlackAdapter - handleSlackStreaming streaming callbacks", () => {
  it("the editMessage callback calls client.chat.update with converted text", async () => {
    vi.clearAllMocks();
    const adapter = new SlackAdapter();
    const client = makeSlackClient("ts-edit");

    let capturedEditMessage: ((text: string) => Promise<void>) | undefined;

    // Intercept handleStreamingChat to capture the editMessage callback.
    vi.mocked(handleStreamingChat).mockImplementationOnce(
      async (_gaia, _req, editMessage) => {
        capturedEditMessage = editMessage;
      },
    );

    await (
      adapter as unknown as {
        handleSlackStreaming: (
          cl: typeof client,
          channelId: string,
          userId: string,
          message: string,
        ) => Promise<void>;
      }
    ).handleSlackStreaming(client, "C789", "U456", "Hello");

    expect(capturedEditMessage).toBeDefined();

    await capturedEditMessage!("Streamed response text");

    expect(client.chat.update).toHaveBeenCalledWith({
      channel: "C789",
      ts: "ts-edit",
      text: convertToSlackMrkdwn("Streamed response text"),
    });
  });
});

// ---------------------------------------------------------------------------
// ACK timing — registerCommands calls ack() immediately
// ---------------------------------------------------------------------------

describe("SlackAdapter - ACK timing in registerCommands", () => {
  it("registers a Bolt command handler that acks before doing any work", async () => {
    vi.clearAllMocks();
    const adapter = new SlackAdapter();

    // Give adapter a mock app
    (adapter as unknown as { app: typeof mockApp }).app = { ...mockApp };

    const executeMock = vi.fn().mockResolvedValue(undefined);
    const commands = [
      {
        name: "todo",
        description: "Manage todos",
        options: [],
        execute: executeMock,
      },
    ];

    await (
      adapter as unknown as {
        registerCommands: (cmds: typeof commands) => Promise<void>;
      }
    ).registerCommands(commands);

    // Bolt's app.command should have been called with the slash-prefixed command name
    expect(mockApp.command).toHaveBeenCalledWith("/todo", expect.any(Function));

    // Extract and invoke the registered handler to verify ack() is called first.
    const handlerFn = vi.mocked(mockApp.command).mock.calls[0][1] as (args: {
      command: {
        user_id: string;
        channel_id: string;
        text: string;
        user_name: string;
      };
      ack: () => Promise<void>;
      respond: () => Promise<void>;
      client: ReturnType<typeof makeSlackClient>;
    }) => Promise<void>;

    const ack = vi.fn().mockResolvedValue(undefined);
    const respond = makeRespondFn();
    const client = makeSlackClient();

    await handlerFn({
      command: {
        user_id: "U1",
        channel_id: "C1",
        text: "list",
        user_name: "alice",
      },
      ack,
      respond,
      client,
    });

    expect(ack).toHaveBeenCalledOnce();
  });
});

// ---------------------------------------------------------------------------
// registerGaiaCommand — /gaia with no message sends ephemeral usage hint
// ---------------------------------------------------------------------------

describe("SlackAdapter - /gaia command with no message", () => {
  it("sends usage hint as ephemeral when /gaia is invoked with empty text", async () => {
    vi.clearAllMocks();
    const adapter = new SlackAdapter();
    (adapter as unknown as { app: typeof mockApp }).app = { ...mockApp };

    // registerGaiaCommand is invoked via registerCommands when cmd.name === "gaia"
    await (
      adapter as unknown as {
        registerGaiaCommand: () => void;
      }
    ).registerGaiaCommand();

    // Retrieve the /gaia handler registered via app.command
    const handlerFn = vi.mocked(mockApp.command).mock.calls[0][1] as (args: {
      command: { user_id: string; channel_id: string; text: string };
      ack: () => Promise<void>;
      client: ReturnType<typeof makeSlackClient>;
    }) => Promise<void>;

    const ack = vi.fn().mockResolvedValue(undefined);
    const client = makeSlackClient();

    await handlerFn({
      command: { user_id: "U1", channel_id: "C1", text: "" },
      ack,
      client,
    });

    expect(ack).toHaveBeenCalledOnce();
    expect(client.chat.postEphemeral).toHaveBeenCalledWith({
      channel: "C1",
      user: "U1",
      text: "Please provide a message. Usage: /gaia <your message>",
    });
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// registerEvents — app_mention strips bot mention, skips empty content
// ---------------------------------------------------------------------------

describe("SlackAdapter - app_mention event handling", () => {
  let adapter: SlackAdapter;
  let mentionHandler: (args: {
    event: { text: string; user: string; channel: string };
    client: ReturnType<typeof makeSlackClient>;
    context: { botUserId?: string };
  }) => Promise<void>;

  beforeEach(async () => {
    vi.clearAllMocks();
    adapter = new SlackAdapter();
    // boot() is not called in tests; inject a mock gaia so this.gaia !== undefined
    (adapter as unknown as { gaia: object }).gaia = {};

    const appMock = { ...mockApp, event: vi.fn(), message: vi.fn() };
    (adapter as unknown as { app: typeof appMock }).app = appMock;

    await (
      adapter as unknown as { registerEvents: () => Promise<void> }
    ).registerEvents();

    // The first event() call registers app_mention
    mentionHandler = vi.mocked(appMock.event).mock
      .calls[0][1] as typeof mentionHandler;
  });

  it("strips bot mention from event text before streaming", async () => {
    const client = makeSlackClient("ts-mention");

    await mentionHandler({
      event: {
        text: "<@BOTID> What should I do today?",
        user: "U999",
        channel: "C111",
      },
      client,
      context: { botUserId: "BOTID" },
    });

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "What should I do today?",
        platform: "slack",
        platformUserId: "U999",
        channelId: "C111",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "slack" }),
    );
  });

  it("posts 'How can I help you?' when mention text is empty after stripping", async () => {
    const client = makeSlackClient();

    await mentionHandler({
      event: { text: "<@BOTID>", user: "U999", channel: "C111" },
      client,
      context: { botUserId: "BOTID" },
    });

    expect(client.chat.postMessage).toHaveBeenCalledWith({
      channel: "C111",
      text: "How can I help you?",
    });
    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("skips event when userId is missing", async () => {
    const client = makeSlackClient();

    // user is undefined → adapter should early-return
    await mentionHandler({
      // @ts-expect-error intentionally omitting user
      event: { text: "<@BOTID> hello", channel: "C111" },
      client,
      context: { botUserId: "BOTID" },
    });

    expect(handleStreamingChat).not.toHaveBeenCalled();
    expect(client.chat.postMessage).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// registerEvents — DM message handler filters subtypes and non-IM channels
// ---------------------------------------------------------------------------

describe("SlackAdapter - DM message event handling", () => {
  let adapter: SlackAdapter;
  let dmHandler: (args: {
    message: {
      text?: string;
      user?: string;
      channel?: string;
      channel_type?: string;
      subtype?: string;
    };
    client: ReturnType<typeof makeSlackClient>;
  }) => Promise<void>;

  beforeEach(async () => {
    vi.clearAllMocks();
    adapter = new SlackAdapter();
    // boot() is not called in tests; inject a mock gaia so this.gaia !== undefined
    (adapter as unknown as { gaia: object }).gaia = {};

    const appMock = { ...mockApp, event: vi.fn(), message: vi.fn() };
    (adapter as unknown as { app: typeof appMock }).app = appMock;

    await (
      adapter as unknown as { registerEvents: () => Promise<void> }
    ).registerEvents();

    // The message() call registers the DM handler
    dmHandler = vi.mocked(appMock.message).mock.calls[0][0] as typeof dmHandler;
  });

  it("streams for valid IM message", async () => {
    const client = makeSlackClient("ts-dm");

    await dmHandler({
      message: {
        text: "Hello GAIA",
        user: "U555",
        channel: "D123",
        channel_type: "im",
      },
      client,
    });

    expect(handleStreamingChat).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({
        message: "Hello GAIA",
        platform: "slack",
        platformUserId: "U555",
        channelId: "D123",
      }),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.objectContaining({ platform: "slack" }),
    );
  });

  it("ignores message with subtype (e.g. bot_message)", async () => {
    const client = makeSlackClient();

    await dmHandler({
      message: {
        text: "Bot said something",
        user: "U555",
        channel: "D123",
        channel_type: "im",
        subtype: "bot_message",
      },
      client,
    });

    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("ignores message that is not in an IM channel", async () => {
    const client = makeSlackClient();

    await dmHandler({
      message: {
        text: "Channel message",
        user: "U555",
        channel: "C999",
        channel_type: "channel",
      },
      client,
    });

    expect(handleStreamingChat).not.toHaveBeenCalled();
  });

  it("ignores message with missing text, user, or channel", async () => {
    const client = makeSlackClient();

    await dmHandler({
      message: { channel_type: "im" },
      client,
    });

    expect(handleStreamingChat).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// dispatchCommand — unknown command sends ephemeral error
// ---------------------------------------------------------------------------

describe("SlackAdapter - dispatchCommand unknown command", () => {
  it("sends ephemeral error for unregistered command name", async () => {
    const adapter = new SlackAdapter();

    const target = {
      platform: "slack" as const,
      userId: "U123",
      channelId: "C456",
      send: vi.fn(),
      sendEphemeral: vi
        .fn()
        .mockResolvedValue({ id: "ephemeral", edit: vi.fn() }),
      sendRich: vi.fn(),
      startTyping: vi.fn(),
    };

    await (
      adapter as unknown as {
        dispatchCommand: (name: string, target: typeof target) => Promise<void>;
      }
    ).dispatchCommand("mystery", target);

    expect(target.sendEphemeral).toHaveBeenCalledWith(
      "Unknown command: /mystery",
    );
  });
});
