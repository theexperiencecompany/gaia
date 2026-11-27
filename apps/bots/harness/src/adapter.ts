/**
 * Harness bot adapter — a fifth {@link BaseBotAdapter} that drives the *real*
 * shared bot pipeline while recording a JSONL transcript instead of talking to
 * a platform SDK.
 *
 * It emulates one platform at a time (`--emulate telegram`), so `this.platform`
 * IS the emulated platform: the shared `GaiaClient` authenticates as that
 * platform (`X-Bot-Platform: telegram`), the outbound consumer binds that
 * platform's real RabbitMQ queue, and streaming runs that platform's real
 * `STREAMING_DEFAULTS` / markdown converter / length limit. Everything a real
 * adapter would do to the backend, the harness does — the only substitution is
 * the platform's send primitive, replaced by a transcript recorder.
 *
 * @module
 */

import { randomUUID } from "node:crypto";
import {
  type ActiveBotConversation,
  BaseBotAdapter,
  type BotCommand,
  type BotFileData,
  type BotLogger,
  buildAuthLinkMessage,
  type ConversationSurface,
  createBotLogger,
  extractSubcommandArgs,
  type OutboundFile,
  type PlatformName,
  REACTION_OUTCOME,
  type ReactionOutcome,
  type RichMessage,
  type RichMessageTarget,
  richMessageToMarkdown,
  type SentMessage,
  withTimeout,
} from "@gaia/shared/bots";
import type { PlatformEmulation } from "./emulation";
import type { PlatformOutage } from "./scenario.types";
import type { TranscriptRecorder } from "./transcript";

/**
 * Port 0: the OS picks a free one. Nothing calls the harness's health server,
 * and a fixed port made a second concurrent sender (a "stop" sent mid-run)
 * die on EADDRINUSE while its outbound consumer kept taking the first run's
 * replies. The runner clears `BOT_SERVER_PORT`, which would override it.
 */
const HARNESS_SERVER_PORT = 0;

/** How long a turn may keep answering before the harness fails it: a long research turn fits. */
const TURN_SETTLE_TIMEOUT_MS = 10 * 60_000;

/** Options accepted by {@link HarnessAdapter.simulateMessage}. */
export interface SimulateOptions {
  /** Channel/conversation id; defaults to the user id (DM-style). */
  channelId?: string;
  /** Files already uploaded to GAIA, forwarded with the chat request. */
  attachments?: BotFileData[];
}

export class HarnessAdapter extends BaseBotAdapter {
  readonly platform: PlatformName;
  protected readonly defaultServerPort = HARNESS_SERVER_PORT;
  private readonly emulation: PlatformEmulation;
  private readonly transcript: TranscriptRecorder;
  private readonly adapterLogger: BotLogger;
  /** What is left of a scripted outage: the platform refuses this many more sends and edits. */
  private outage: PlatformOutage | null = null;
  /** A react call held open, as a bot dies inside it: a restart turn kills the bot there. */
  private reactionHold: {
    started: () => void;
    die: ((error: Error) => void) | null;
  } | null = null;
  /** The boot's resume of conversations still answering; settled before boot starts one. */
  private resumed: Promise<void> = Promise.resolve();
  // Platform message ids are deduplicated per conversation, so each run names its own.
  private readonly runId = randomUUID().slice(0, 8);

  protected override readonly consumesOutbound: boolean;

  /**
   * consumesOutbound is false for a message sent into a conversation another
   * harness process is already consuming for: RabbitMQ would split that
   * process's deliveries between the two.
   */
  constructor(
    emulation: PlatformEmulation,
    transcript: TranscriptRecorder,
    { consumesOutbound = true }: { consumesOutbound?: boolean } = {},
  ) {
    super();
    this.consumesOutbound = consumesOutbound;
    this.platform = emulation.platform;
    this.emulation = emulation;
    this.transcript = transcript;
    this.adapterLogger = createBotLogger(emulation.platform, "harness-adapter");
  }

  // ---------------------------------------------------------------------------
  // Lifecycle — no platform gateway; the CLI injects messages directly.
  // ---------------------------------------------------------------------------

  protected initialize(): Promise<void> {
    this.adapterLogger.info("harness_initialized", {
      emulating: this.platform,
      limit: this.emulation.limit,
      streaming: this.emulation.streaming.streaming,
    });
    return Promise.resolve();
  }

  protected registerCommands(_commands: BotCommand[]): Promise<void> {
    return Promise.resolve();
  }

  protected registerEvents(): Promise<void> {
    return Promise.resolve();
  }

  protected start(): Promise<void> {
    return Promise.resolve();
  }

  protected stop(): Promise<void> {
    return Promise.resolve();
  }

  /**
   * Records a backend-originated (proactive) delivery. Invoked by the real
   * outbound RabbitMQ consumer that {@link BaseBotAdapter.boot} starts, so
   * proactive notifications land in the transcript exactly like request/response
   * replies. `text` is already rendered by the consumer for this platform.
   */
  protected deliverOutbound(
    destinationId: string,
    text: string,
  ): Promise<void> {
    this.transcript.record({
      type: "outbound-delivery",
      destinationId,
      text,
    });
    return Promise.resolve();
  }

  /**
   * Records a backend-originated file delivery, after the base class fetched
   * the bytes through the real shared helper. The harness stands in for a
   * platform that can send files, so a transcript has to show the caption and
   * prove the download succeeded.
   */
  protected override sendOutboundFile(
    destinationId: string,
    { data, mime, filename, caption }: OutboundFile,
  ): Promise<void> {
    this.transcript.record({
      type: "outbound-attachment",
      destinationId,
      filename,
      text: caption ?? "",
      bytes: data.length,
      contentType: mime,
    });
    return Promise.resolve();
  }

  /**
   * Records a native reaction. Every emulated platform has a reaction API, so
   * live acks and outbound reactions both land as `reaction` events.
   */
  protected override reactToMessage(
    destinationId: string,
    platformMessageId: string,
    emoji: string,
    _isChannel: boolean,
    replaces: string | null,
  ): Promise<ReactionOutcome> {
    const hold = this.reactionHold;
    if (hold && !hold.die) {
      return new Promise((_resolve, reject) => {
        hold.die = reject;
        hold.started();
      });
    }
    this.transcript.record({
      type: "reaction",
      destinationId,
      targetMessageId: platformMessageId,
      emoji,
      replaces,
    });
    return Promise.resolve(REACTION_OUTCOME.ATTACHED);
  }

  // ---------------------------------------------------------------------------
  // Inbound simulation
  // ---------------------------------------------------------------------------

  /**
   * Injects one inbound message as `userId`, recorded the moment it arrives, and
   * resolves once it is handled: a chat message is posted, in arrival order,
   * and followed in the background, as every real adapter does. {@link conversationsIdle} waits for
   * the replies.
   */
  simulateMessage(
    userId: string,
    text: string,
    options: SimulateOptions = {},
  ): Promise<void> {
    const channelId = options.channelId ?? userId;
    const messageId = this.transcript.newMessageId(`in-${this.runId}-`);
    this.transcript.record({
      type: "inbound",
      userId,
      channelId,
      messageId,
      text,
    });
    return this.arrivals.run(userId, () =>
      this.handleInbound(userId, channelId, messageId, text, options),
    );
  }

  /** Records the boot's resume of the conversations still answering, so a turn can wait for it. */
  protected override resumeFollows(): Promise<void> {
    this.resumed = super.resumeFollows();
    return this.resumed;
  }

  /** Hold the next react call open, placing nothing; resolves once one is held. */
  holdNextReaction(): Promise<void> {
    return new Promise((started) => {
      this.reactionHold = { started, die: null };
    });
  }

  /** End the held react call as the bot process dying inside it would: nothing after it runs. */
  dieInHeldReaction(): void {
    this.reactionHold?.die?.(
      new Error("bot process died inside the react call"),
    );
  }

  /** From now, the platform refuses the next `outage.failures` sends and edits with `outage.status`. */
  startOutage(outage: PlatformOutage): void {
    this.outage = { ...outage };
  }

  /**
   * Throws the platform's error while a scripted outage lasts, shaped as
   * grammY's GrammyError: a `description` and the HTTP status as `error_code`.
   */
  private refuseDuringOutage(call: "send" | "edit"): void {
    if (!this.outage || this.outage.failures <= 0) return;
    this.outage.failures -= 1;
    const { status } = this.outage;
    this.transcript.record({ type: "platform-failure", call, status });
    const description = `Bad Gateway: the platform answered ${status}`;
    throw Object.assign(
      new Error(`Call to '${call}Message' failed! (${status}: ${description})`),
      { error_code: status, description },
    );
  }

  /**
   * Waits until every followed conversation is idle, or parked on approvals GAIA asked
   * the user about, which it records as an awaiting-approval event each. A conversation
   * still answering after timeoutMs fails the turn instead of hanging the run.
   */
  async settleTurn(timeoutMs = TURN_SETTLE_TIMEOUT_MS): Promise<void> {
    // A booted bot resumes in the background; its follows count once they start.
    await this.resumed;
    const awaited = await withTimeout(
      this.conversationsSettled(),
      timeoutMs,
      `the conversation was still answering after ${timeoutMs} ms`,
    );
    for (const { conversationId, approvals } of awaited) {
      this.transcript.record({
        type: "awaiting-approval",
        conversationId,
        approvals: approvals.map(({ approval_id, description }) => ({
          approvalId: approval_id,
          headline: description.headline,
        })),
      });
    }
  }

  /**
   * Routes one inbound message through the real shared pipeline exactly as the
   * Telegram/WhatsApp adapters route inbound text: a `/command` (other than
   * `/gaia`) dispatches through the unified command system; everything else
   * (including `/gaia <text>`) streams a chat turn.
   */
  private async handleInbound(
    userId: string,
    channelId: string,
    messageId: string,
    text: string,
    options: SimulateOptions,
  ): Promise<void> {
    if (text.startsWith("/")) {
      const withoutSlash = text.slice(1);
      const spaceIndex = withoutSlash.indexOf(" ");
      const commandName = (
        spaceIndex === -1 ? withoutSlash : withoutSlash.slice(0, spaceIndex)
      ).toLowerCase();
      const rest =
        spaceIndex === -1 ? "" : withoutSlash.slice(spaceIndex + 1).trim();

      if (commandName !== "gaia") {
        const target = this.createTarget(userId, channelId);
        const args = extractSubcommandArgs(commandName, rest);
        await this.dispatchCommand(
          commandName,
          target,
          args,
          rest || undefined,
        );
        return;
      }
      await this.postTurn(
        userId,
        channelId,
        messageId,
        rest,
        options.attachments,
      );
      return;
    }

    await this.postTurn(
      userId,
      channelId,
      messageId,
      text,
      options.attachments,
    );
  }

  /**
   * Posts one chat message through the shared {@link BaseBotAdapter.postAndFollow},
   * recording every message the emulated platform would show. Text reaches the
   * surface already converted by the platform's markdown converter, so the
   * transcript stores exactly what the platform SDK would receive.
   */
  private postTurn(
    userId: string,
    channelId: string,
    inboundMessageId: string,
    message: string,
    attachments: BotFileData[] = [],
  ): Promise<void> {
    const surface = this.conversationSurface(channelId);
    return this.postAndFollow(
      {
        message,
        platform: this.platform,
        platformUserId: userId,
        channelId,
        platformMessageId: inboundMessageId,
        ...(attachments.length > 0
          ? { fileIds: attachments.map((a) => a.fileId), fileData: attachments }
          : {}),
      },
      surface,
      async (authUrl: string) => {
        // Every real adapter renders buildAuthLinkMessage through the platform converter.
        await surface.send(
          this.emulation.render(buildAuthLinkMessage(authUrl)),
          null,
        );
      },
    );
  }

  protected async resumeSurface({
    platform_user_id: userId,
    channel_id: channelId,
  }: ActiveBotConversation): Promise<ConversationSurface> {
    return this.conversationSurface(channelId ?? userId);
  }

  /**
   * The emulated chat a conversation follows into. Without edit support
   * (WhatsApp, iMessage) an "edit" is a new message.
   */
  private conversationSurface(channelId: string): ConversationSurface {
    const record = (text: string, replyTo: string | null): string => {
      this.refuseDuringOutage("send");
      const id = this.transcript.newMessageId("m");
      this.transcript.record({
        type: "send",
        messageId: id,
        text,
        length: text.length,
        ...(replyTo ? { replyTo } : {}),
      });
      return id;
    };
    const bubble = (id: string) => ({
      id,
      // A refused call rejects, as a platform SDK's does.
      edit: (updated: string) =>
        new Promise<void>((resolve) => {
          if (!this.emulation.supportsEdit) {
            record(updated, null);
          } else {
            this.refuseDuringOutage("edit");
            this.transcript.record({
              type: "edit",
              messageId: id,
              text: updated,
              length: updated.length,
            });
          }
          resolve();
        }),
    });
    return {
      send: (text, replyTo) =>
        new Promise((resolve) => resolve(bubble(record(text, replyTo)))),
      reopen: (id) => ({
        ...bubble(id),
        delete: () => {
          this.transcript.record({ type: "delete", messageId: id });
          return Promise.resolve();
        },
      }),
      react: (platformMessageId, emoji, replaces) =>
        this.reactToMessage(
          channelId,
          platformMessageId,
          emoji,
          false,
          replaces,
        ),
      startTyping: (answering) => {
        this.transcript.record({
          type: "typing",
          state: "start",
          ...(answering ? { answering } : {}),
        });
        return () => this.transcript.record({ type: "typing", state: "stop" });
      },
    };
  }

  /**
   * Builds a {@link RichMessageTarget} for the unified command path (`/todo`,
   * `/help`, `/auth`, …). Non-streaming sends are rendered here through the
   * platform converter, mirroring every real adapter's `renderForPlatform`
   * chokepoint.
   */
  private createTarget(userId: string, channelId: string): RichMessageTarget {
    const makeSent = (id: string): SentMessage => ({
      id,
      edit: (t: string) => {
        this.transcript.record({
          type: "edit",
          messageId: id,
          text: this.emulation.render(t),
          length: this.emulation.render(t).length,
        });
        return Promise.resolve();
      },
    });

    return {
      platform: this.platform,
      userId,
      channelId,

      send: (text: string): Promise<SentMessage> => {
        const rendered = this.emulation.render(text);
        const id = this.transcript.newMessageId("m");
        this.transcript.record({
          type: "send",
          messageId: id,
          text: rendered,
          length: rendered.length,
        });
        return Promise.resolve(makeSent(id));
      },

      sendEphemeral: (text: string): Promise<SentMessage> => {
        const rendered = this.emulation.render(text);
        this.transcript.record({ type: "ephemeral", text: rendered });
        return Promise.resolve(makeSent(this.transcript.newMessageId("e")));
      },

      sendRich: (message: RichMessage): Promise<SentMessage> => {
        const rendered = this.emulation.render(richMessageToMarkdown(message));
        this.transcript.record({
          type: "rich",
          title: message.title,
          text: rendered,
        });
        return Promise.resolve(makeSent(this.transcript.newMessageId("r")));
      },

      startTyping: () => {
        this.transcript.record({ type: "typing", state: "start" });
        return Promise.resolve(() => {
          this.transcript.record({ type: "typing", state: "stop" });
        });
      },
    };
  }
}
