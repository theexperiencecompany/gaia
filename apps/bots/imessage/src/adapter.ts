import {
  BaseBotAdapter,
  BODY_READ_TIMEOUT,
  BODY_TOO_LARGE,
  type BotCommand,
  type BotFileData,
  buildAuthLinkMessage,
  createBotLogger,
  extractSubcommandArgs,
  friendlyMediaError,
  handleStreamingChat,
  hashLogIdentifier,
  type IncomingMedia,
  mediaKindFromMime,
  type OutboundAttachment,
  type PlatformName,
  type RichMessage,
  type RichMessageTarget,
  readBodyBytesBounded,
  renderForPlatform,
  richMessageToMarkdown,
  type SentMessage,
  STREAMING_DEFAULTS,
  sanitizeErrorForLog,
  unsupportedMediaMessage,
  WEBHOOK_MAX_BODY_BYTES,
  wideLog,
  withWideEvent,
} from "@gaia/shared";
import {
  type Attachment,
  attachment,
  type Message,
  type Space,
  Spectrum,
} from "spectrum-ts";
import { imessage } from "spectrum-ts/providers/imessage";
import {
  IMESSAGE_SERVER_PORT,
  RECENT_MESSAGE_IDS_MAX,
  WELCOME_AUTH_CHECK_TIMEOUT_MS,
} from "./constants";

interface ImessageConfig {
  projectId: string;
  projectSecret: string;
  webhookSecret: string;
}

function loadImessageConfig(): ImessageConfig {
  const projectId = process.env.SPECTRUM_PROJECT_ID;
  const projectSecret = process.env.SPECTRUM_PROJECT_SECRET;
  const webhookSecret = process.env.SPECTRUM_WEBHOOK_SECRET;

  if (!projectId) throw new Error("SPECTRUM_PROJECT_ID is required");
  if (!projectSecret) throw new Error("SPECTRUM_PROJECT_SECRET is required");
  if (!webhookSecret) throw new Error("SPECTRUM_WEBHOOK_SECRET is required");

  return { projectId, projectSecret, webhookSecret };
}

async function createSpectrumApp(config: ImessageConfig) {
  return Spectrum({
    projectId: config.projectId,
    projectSecret: config.projectSecret,
    webhookSecret: config.webhookSecret,
    providers: [imessage.config()],
  });
}

type SpectrumApp = Awaited<ReturnType<typeof createSpectrumApp>>;
type ImessageInstance = ReturnType<typeof imessage<SpectrumApp["__providers"]>>;

export class ImessageAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "imessage";
  protected readonly defaultServerPort = IMESSAGE_SERVER_PORT;

  private spectrumApp: SpectrumApp | null = null;
  private imInstance: ImessageInstance | null = null;

  private readonly linkedUsers = new Set<string>();
  private readonly messageQueues = new Map<string, Promise<void>>();
  private readonly recentMessageIds = new Set<string>();
  private readonly adapterLogger = createBotLogger("imessage", "adapter");

  private get app(): SpectrumApp {
    if (!this.spectrumApp) {
      throw new Error("Spectrum app not initialized — call boot() first");
    }
    return this.spectrumApp;
  }

  private get im(): ImessageInstance {
    if (!this.imInstance) {
      throw new Error("Spectrum app not initialized — call boot() first");
    }
    return this.imInstance;
  }

  protected async initialize(): Promise<void> {
    const config = loadImessageConfig();
    this.spectrumApp = await createSpectrumApp(config);
    this.imInstance = imessage(this.spectrumApp);
    wideLog.set({ project_id: config.projectId });
  }

  protected registerCommands(_commands: BotCommand[]): Promise<void> {
    return Promise.resolve();
  }

  protected async registerEvents(): Promise<void> {
    this.botServer.app.post("/webhook", async (c) =>
      withWideEvent(
        "webhook",
        { platform: "imessage", component: "adapter" },
        async () => {
          const contentLength = Number(c.req.header("content-length"));
          if (
            Number.isFinite(contentLength) &&
            contentLength > WEBHOOK_MAX_BODY_BYTES
          ) {
            this.adapterLogger.warn("webhook_body_too_large", {
              content_length: contentLength,
              max_bytes: WEBHOOK_MAX_BODY_BYTES,
            });
            wideLog.set({ http_status: 413 });
            return c.text("Payload Too Large", 413);
          }

          const rawBody = await readBodyBytesBounded(
            c.req.raw,
            WEBHOOK_MAX_BODY_BYTES,
          );
          if (rawBody === BODY_TOO_LARGE) {
            this.adapterLogger.warn("webhook_body_too_large", {
              max_bytes: WEBHOOK_MAX_BODY_BYTES,
            });
            wideLog.set({ http_status: 413 });
            return c.text("Payload Too Large", 413);
          }
          if (rawBody === BODY_READ_TIMEOUT) {
            this.adapterLogger.warn("webhook_body_read_timeout");
            wideLog.set({ http_status: 408 });
            return c.text("Request Timeout", 408);
          }

          const result = await this.app.webhook(
            { body: rawBody, headers: c.req.header() },
            (space, message) => this.handleInboundMessage(space, message),
          );
          if (result.status === 401) {
            wideLog.audit("webhook_signature_rejected", {
              has_signature: c.req.header("x-spectrum-signature") !== undefined,
            });
          }
          wideLog.set({ http_status: result.status });
          return c.newResponse(
            new Uint8Array(result.body).buffer,
            result.status as 200,
            result.headers,
          );
        },
      ),
    );
  }

  protected start(): Promise<void> {
    return Promise.resolve();
  }

  protected stop(): Promise<void> {
    return Promise.resolve();
  }

  private handleInboundMessage(space: Space, message: Message): void {
    if (message.direction === "outbound" || message.sender?.kind === "agent") {
      return;
    }
    const handle = message.sender?.id;
    if (!handle) return;
    if (this.recentMessageIds.has(message.id)) return;
    this.recentMessageIds.add(message.id);
    if (this.recentMessageIds.size > RECENT_MESSAGE_IDS_MAX) {
      const oldest = this.recentMessageIds.values().next().value;
      if (oldest) this.recentMessageIds.delete(oldest);
    }

    const imSpace = imessage(space);
    if (imSpace.type === "group") return;

    const handleHash = hashLogIdentifier(handle);
    const content = message.content;
    this.adapterLogger.info("webhook_message_received", {
      user_hash: handleHash,
      message_type: content.type,
    });

    if (content.type === "text" || content.type === "markdown") {
      const text = content.type === "text" ? content.text : content.markdown;
      this.enqueueForUser(handle, () =>
        this.handleIncomingMessage(handle, space, text).catch((err) =>
          this.adapterLogger.error("incoming_message_processing_failed", {
            user_hash: handleHash,
            message_id: message.id,
            ...sanitizeErrorForLog(err),
          }),
        ),
      );
      return;
    }

    if (content.type === "attachment") {
      this.enqueueForUser(handle, () =>
        this.handleMediaMessage(handle, space, content).catch((err) =>
          this.adapterLogger.error("media_message_processing_failed", {
            user_hash: handleHash,
            message_id: message.id,
            ...sanitizeErrorForLog(err),
          }),
        ),
      );
      return;
    }

    if (content.type === "group" || content.type === "contact") {
      this.enqueueForUser(handle, async () => {
        try {
          await this.sendImessageText(
            space,
            unsupportedMediaMessage(content.type),
          );
        } catch (err) {
          this.adapterLogger.error("unsupported_media_handling_failed", {
            user_hash: handleHash,
            message_type: content.type,
            ...sanitizeErrorForLog(err),
          });
        }
      });
    }
  }

  private enqueueForUser(handle: string, fn: () => Promise<void>): void {
    const previous = this.messageQueues.get(handle) ?? Promise.resolve();
    const task = previous.catch(() => undefined).then(() => fn());
    this.messageQueues.set(handle, task);
    task.then(
      () => {
        if (this.messageQueues.get(handle) === task)
          this.messageQueues.delete(handle);
      },
      () => {
        if (this.messageQueues.get(handle) === task)
          this.messageQueues.delete(handle);
      },
    );
  }

  private async handleIncomingMessage(
    handle: string,
    space: Space,
    text: string,
  ): Promise<void> {
    const handleHash = hashLogIdentifier(handle);
    this.adapterLogger.info("incoming_message_started", {
      user_hash: handleHash,
      text_length: text.length,
      is_command: text.startsWith("/"),
    });

    await space.startTyping().catch((err: unknown) =>
      this.adapterLogger.error("typing_indicator_failed", {
        user_hash: handleHash,
        ...sanitizeErrorForLog(err),
      }),
    );

    try {
      await this.ensureWelcomed(handle, space);

      const target = this.createImessageTarget(handle, space);

      if (text.startsWith("/")) {
        const withoutSlash = text.slice(1);
        const spaceIndex = withoutSlash.indexOf(" ");
        const commandName = (
          spaceIndex === -1 ? withoutSlash : withoutSlash.slice(0, spaceIndex)
        ).toLowerCase();
        const rest =
          spaceIndex === -1 ? "" : withoutSlash.slice(spaceIndex + 1).trim();

        if (commandName === "gaia") {
          if (!rest) {
            await this.sendImessageText(space, "Usage: /gaia <your message>");
            return;
          }
          await this.handleStreamingMessage(handle, space, rest);
          return;
        }

        const args = extractSubcommandArgs(commandName, rest);
        await this.dispatchCommand(
          commandName,
          target,
          args,
          rest || undefined,
        );
        return;
      }

      await this.handleStreamingMessage(handle, space, text);
    } finally {
      await space.stopTyping().catch(() => undefined);
    }
  }

  private async handleStreamingMessage(
    handle: string,
    space: Space,
    text: string,
    attachments: BotFileData[] = [],
  ): Promise<void> {
    if (!text.trim() && attachments.length === 0) {
      await this.sendImessageText(
        space,
        "Hi! Send me a message and I'll help you. Type /help for available commands.",
      );
      return;
    }

    let lastEditFn: ((t: string) => Promise<void>) | null = null;
    let finalMessageSent = false;

    try {
      await handleStreamingChat(
        this.gaia,
        {
          message: text || "Please describe the attached file.",
          platform: "imessage",
          platformUserId: handle,
          channelId: space.id,
          ...(attachments.length > 0
            ? {
                fileIds: attachments.map((a) => a.fileId),
                fileData: attachments,
              }
            : {}),
        },
        async (formatted: string) => {
          if (finalMessageSent) return;
          finalMessageSent = true;
          if (lastEditFn) {
            await lastEditFn(formatted);
          } else {
            const sent = await this.sendImessageText(space, formatted);
            lastEditFn = sent.edit;
          }
        },
        async (newText: string) => {
          const sent = await this.sendImessageText(space, newText);
          lastEditFn = sent.edit;
          return sent.edit;
        },
        async (authUrl: string) => {
          await this.sendImessageText(
            space,
            renderForPlatform(buildAuthLinkMessage(authUrl), "imessage"),
          );
        },
        async (errMsg: string) => {
          await this.sendImessageText(space, errMsg);
        },
        STREAMING_DEFAULTS.imessage,
        this.analytics,
      );
    } catch (err) {
      this.adapterLogger.error("streaming_failed", {
        user_hash: hashLogIdentifier(handle),
        ...sanitizeErrorForLog(err),
      });
      try {
        await this.sendImessageText(
          space,
          "An error occurred. Please try again.",
        );
      } catch (sendErr) {
        this.adapterLogger.error("streaming_error_message_send_failed", {
          user_hash: hashLogIdentifier(handle),
          ...sanitizeErrorForLog(sendErr),
        });
      }
    }
  }

  private async ensureWelcomed(handle: string, space: Space): Promise<void> {
    if (!(await this.shouldSendWelcome(handle))) return;

    let isLinked = this.linkedUsers.has(handle);
    if (!isLinked) {
      isLinked = await this.isUserLinked(handle, WELCOME_AUTH_CHECK_TIMEOUT_MS);
    }
    if (!isLinked) {
      await this.sendWelcome(space, handle);
    }
  }

  private async isUserLinked(
    handle: string,
    timeoutMs: number,
  ): Promise<boolean> {
    try {
      const status = await Promise.race([
        this.gaia.checkAuthStatus("imessage", handle),
        new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error("auth_check_timeout")), timeoutMs),
        ),
      ]);
      if (status.authenticated) this.linkedUsers.add(handle);
      return status.authenticated;
    } catch (err) {
      this.adapterLogger.warn("welcome_auth_check_failed", {
        user_hash: hashLogIdentifier(handle),
        ...sanitizeErrorForLog(err),
      });
      return false;
    }
  }

  private async sendWelcome(space: Space, handle: string): Promise<void> {
    const text =
      "Hey, I'm GAIA 👋\n\n" +
      "Your personal AI — I think ahead, remember what matters, and help you actually get things done.\n\n" +
      "Here's what I can do right here on iMessage:\n\n" +
      "Chat\nJust type anything — ask questions, brainstorm, think out loud.\n\n" +
      "Todos\nCapture tasks with /todo add.\n\n" +
      "Workflows\nRun automations with /workflow and delegate whole projects.\n\n" +
      "Link your account\nRun /auth to connect GAIA so I remember you and your context.\n\n" +
      "Visit heygaia.io or read the docs at docs.heygaia.io";

    try {
      await this.sendImessageText(space, text);
    } catch (error) {
      this.adapterLogger.error(
        "welcome_send_failed",
        { user_hash: hashLogIdentifier(handle) },
        error,
      );
    }
  }

  private async handleMediaMessage(
    handle: string,
    space: Space,
    content: Attachment,
  ): Promise<void> {
    const handleHash = hashLogIdentifier(handle);
    const kind = mediaKindFromMime(content.mimeType);
    this.adapterLogger.info("media_message_started", {
      user_hash: handleHash,
      media_kind: kind,
      mime_type: content.mimeType,
    });

    await space.startTyping().catch(() => undefined);

    try {
      await this.ensureWelcomed(handle, space);

      const incoming: IncomingMedia = {
        kind,
        isVoiceNote: false,
        mimeType: content.mimeType,
        filename: content.name,
      };
      const outcome = await this.resolveIncomingMedia(
        incoming,
        async () => new Uint8Array(await content.read()),
        handle,
        space.id,
      );

      if (outcome.action === "reply") {
        await this.sendImessageText(space, outcome.text);
      } else {
        await this.handleStreamingMessage(
          handle,
          space,
          outcome.text,
          outcome.attachments,
        );
      }
    } catch (err) {
      this.adapterLogger.error("media_message_failed", {
        user_hash: handleHash,
        media_kind: kind,
        ...sanitizeErrorForLog(err),
      });
      try {
        await this.sendImessageText(
          space,
          friendlyMediaError(kind, err, this.gaia.getPricingUrl()),
        );
      } catch (sendErr) {
        this.adapterLogger.error("media_error_message_send_failed", {
          user_hash: handleHash,
          ...sanitizeErrorForLog(sendErr),
        });
      }
    } finally {
      await space.stopTyping().catch(() => undefined);
    }
  }

  private createImessageTarget(
    handle: string,
    space: Space,
  ): RichMessageTarget {
    return {
      platform: "imessage",
      userId: handle,
      channelId: space.id,

      send: async (text: string): Promise<SentMessage> => {
        return this.sendImessageText(
          space,
          renderForPlatform(text, "imessage"),
        );
      },

      sendEphemeral: async (text: string): Promise<SentMessage> => {
        return this.sendImessageText(
          space,
          renderForPlatform(text, "imessage"),
        );
      },

      sendRich: async (richMsg: RichMessage): Promise<SentMessage> => {
        const rendered = renderForPlatform(
          richMessageToMarkdown(richMsg),
          "imessage",
        );
        return this.sendImessageText(space, rendered);
      },

      startTyping: async () => {
        return () => undefined;
      },
    };
  }

  private async sendImessageText(
    space: Space,
    text: string,
  ): Promise<SentMessage> {
    const sent = await space.send(text);

    return {
      id: sent?.id ?? "",
      edit: async (updatedText: string): Promise<void> => {
        await space.send(updatedText);
      },
    };
  }

  protected async deliverOutbound(
    destinationId: string,
    text: string,
  ): Promise<void> {
    const space = await this.im.space.create(destinationId);
    await space.send(text);
  }

  protected override async deliverOutboundFile(
    destinationId: string,
    outboundAttachment: OutboundAttachment,
  ): Promise<void> {
    const artifact = await this.fetchOutboundArtifact(
      destinationId,
      outboundAttachment,
    );
    if (!artifact) return;
    const { data, contentType } = artifact;
    const mime =
      outboundAttachment.content_type ??
      contentType ??
      "application/octet-stream";

    const space = await this.im.space.create(destinationId);
    await space.send(
      attachment(Buffer.from(data), {
        name: outboundAttachment.filename,
        mimeType: mime,
      }),
    );
    if (outboundAttachment.caption) {
      await space.send(outboundAttachment.caption);
    }
  }
}
