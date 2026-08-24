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

import {
  BaseBotAdapter,
  type BotCommand,
  type BotFileData,
  type BotLogger,
  buildAuthLinkMessage,
  createBotLogger,
  extractSubcommandArgs,
  handleStreamingChat,
  type PlatformName,
  type RichMessage,
  type RichMessageTarget,
  richMessageToMarkdown,
  type SentMessage,
} from "@gaia/shared/bots";
import type { PlatformEmulation } from "./emulation";
import type { TranscriptRecorder } from "./transcript";

/** Default HTTP health-server port — high, to avoid the 3200-3203 real bots. */
const HARNESS_SERVER_PORT = 3210;

/** Options accepted by {@link HarnessAdapter.simulateMessage}. */
export interface SimulateOptions {
  /** Channel/conversation id; defaults to the user id (DM-style). */
  channelId?: string;
  /** Files already uploaded to GAIA, forwarded with the chat request. */
  attachments?: BotFileData[];
}

/**
 * A single delivered bubble, tracked during one streaming turn so the harness
 * can (a) apply the emulated platform's edit-vs-send-new semantics and (b) emit
 * a `split` event describing the final multi-bubble layout.
 */
interface Bubble {
  id: string;
  text: string;
}

export class HarnessAdapter extends BaseBotAdapter {
  readonly platform: PlatformName;
  protected readonly defaultServerPort = HARNESS_SERVER_PORT;
  private readonly emulation: PlatformEmulation;
  private readonly transcript: TranscriptRecorder;
  private readonly adapterLogger: BotLogger;
  private nextMessageId = 1;

  constructor(emulation: PlatformEmulation, transcript: TranscriptRecorder) {
    super();
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

  // ---------------------------------------------------------------------------
  // Inbound simulation
  // ---------------------------------------------------------------------------

  /**
   * Injects one inbound message as `userId`, routing it through the real shared
   * pipeline exactly as the Telegram/WhatsApp adapters route inbound text:
   * a `/command` (other than `/gaia`) dispatches through the unified command
   * system; everything else (including `/gaia <text>`) streams a chat turn.
   */
  async simulateMessage(
    userId: string,
    text: string,
    options: SimulateOptions = {},
  ): Promise<void> {
    const channelId = options.channelId ?? userId;
    this.transcript.record({ type: "inbound", userId, channelId, text });

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
      await this.streamTurn(userId, channelId, rest, options.attachments);
      return;
    }

    await this.streamTurn(userId, channelId, text, options.attachments);
  }

  /**
   * Streams one chat turn through the shared {@link handleStreamingChat},
   * recording every bubble the emulated platform would deliver. The callbacks
   * receive text already converted by the platform's markdown converter (the
   * shared streamer renders at its single chokepoint), so the transcript stores
   * exactly what the platform SDK would receive.
   */
  private async streamTurn(
    userId: string,
    channelId: string,
    message: string,
    attachments: BotFileData[] = [],
  ): Promise<void> {
    this.transcript.record({ type: "typing", state: "start" });

    const bubbles: Bubble[] = [];
    let current: Bubble | null = null;

    /** Records a fresh bubble and makes it current. */
    const openBubble = (text: string, isError?: boolean): Bubble => {
      const bubble: Bubble = { id: `m${this.nextMessageId++}`, text };
      bubbles.push(bubble);
      current = bubble;
      this.transcript.record({
        type: "send",
        messageId: bubble.id,
        text,
        length: text.length,
        ...(isError ? { isError } : {}),
      });
      return bubble;
    };

    /** Updates the current bubble in place, or opens one if none exists. */
    const writeCurrent = (text: string, isError?: boolean): void => {
      if (!current) {
        openBubble(text, isError);
        return;
      }
      // No in-place edit support (WhatsApp): an "edit" is a new message.
      if (!this.emulation.supportsEdit) {
        openBubble(text, isError);
        return;
      }
      current.text = text;
      this.transcript.record({
        type: "edit",
        messageId: current.id,
        text,
        length: text.length,
        ...(isError ? { isError } : {}),
      });
    };

    const editMessage = (text: string): Promise<void> => {
      writeCurrent(text);
      return Promise.resolve();
    };

    const sendNewMessage = (
      text: string,
    ): Promise<(t: string) => Promise<void>> => {
      const bubble = openBubble(text);
      return Promise.resolve((updated: string) => {
        // Edit the bubble this send opened (respecting edit support).
        if (this.emulation.supportsEdit) {
          bubble.text = updated;
          this.transcript.record({
            type: "edit",
            messageId: bubble.id,
            text: updated,
            length: updated.length,
          });
        } else {
          openBubble(updated);
        }
        return Promise.resolve();
      });
    };

    const onAuthError = (authUrl: string): Promise<void> => {
      // Every real adapter renders buildAuthLinkMessage through the platform
      // converter before delivering it; do the same so the transcript matches.
      writeCurrent(this.emulation.render(buildAuthLinkMessage(authUrl)));
      return Promise.resolve();
    };

    const onGenericError = (formattedError: string): Promise<void> => {
      writeCurrent(formattedError, true);
      return Promise.resolve();
    };

    await handleStreamingChat(
      this.gaia,
      {
        message,
        platform: this.platform,
        platformUserId: userId,
        channelId,
        ...(attachments.length > 0
          ? { fileIds: attachments.map((a) => a.fileId), fileData: attachments }
          : {}),
      },
      editMessage,
      sendNewMessage,
      onAuthError,
      onGenericError,
      this.emulation.streaming,
      await this.analyticsFor(userId),
    );

    this.transcript.record({ type: "typing", state: "stop" });

    if (bubbles.length > 1) {
      this.transcript.record({
        type: "split",
        segmentCount: bubbles.length,
        segmentLengths: bubbles.map((b) => b.text.length),
        limit: this.emulation.limit,
      });
    }
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
        const id = `m${this.nextMessageId++}`;
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
        return Promise.resolve(makeSent(`e${this.nextMessageId++}`));
      },

      sendRich: (message: RichMessage): Promise<SentMessage> => {
        const rendered = this.emulation.render(richMessageToMarkdown(message));
        this.transcript.record({
          type: "rich",
          title: message.title,
          text: rendered,
        });
        return Promise.resolve(makeSent(`r${this.nextMessageId++}`));
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
