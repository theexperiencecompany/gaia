import { BaseBotAdapter } from "@gaia/shared";
import type { BotCommand, PlatformName } from "@gaia/shared";

export class WhatsAppAdapter extends BaseBotAdapter {
  readonly platform: PlatformName = "whatsapp";

  protected async initialize(): Promise<void> {
    // TODO
  }

  protected async registerCommands(_commands: BotCommand[]): Promise<void> {
    // TODO
  }

  protected async registerEvents(): Promise<void> {
    // TODO
  }

  protected async start(): Promise<void> {
    // TODO
  }

  protected async stop(): Promise<void> {
    // TODO
  }
}
