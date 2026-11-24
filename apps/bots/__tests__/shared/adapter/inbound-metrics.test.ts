/**
 * Every inbound message handled by the shared adapter counts once on
 * gaia_bot_inbound_total, as ok when it finishes and failed when it throws.
 */
import {
  BaseBotAdapter,
  type BotCommand,
  type RichMessageTarget,
} from "@gaia/shared/bots";
import { describe, expect, it, vi } from "vitest";
import {
  BOT_OUTCOME,
  type BotOutcome,
  botRegistry,
} from "../../../../../libs/shared/ts/src/bots/metrics";
import { injectGaia } from "../helpers/inject-gaia";

class CommandAdapter extends BaseBotAdapter {
  readonly platform = "telegram" as const;
  protected readonly defaultServerPort = 3202;

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
  protected async resumeSurface(): Promise<never> {
    throw new Error("not under test");
  }

  run(command: BotCommand): Promise<void> {
    this.commands.set(command.name, command);
    const target = {
      userId: "42",
      channelId: "42",
      isDm: true,
      sendEphemeral: vi.fn().mockResolvedValue(undefined),
    } as unknown as RichMessageTarget;
    return this.dispatchCommand(command.name, target);
  }
}

async function inboundCount(outcome: BotOutcome): Promise<number> {
  const metric = botRegistry.getSingleMetric("gaia_bot_inbound_total");
  const { values } = await (metric as NonNullable<typeof metric>).get();
  return (
    values.find(
      (v) => v.labels.platform === "telegram" && v.labels.outcome === outcome,
    )?.value ?? 0
  );
}

function adapterWithGaia(): CommandAdapter {
  const adapter = new CommandAdapter();
  injectGaia(adapter, { checkAuthStatus: async () => ({ user_id: null }) });
  return adapter;
}

describe("gaia_bot_inbound_total", () => {
  it("counts a handled command as ok", async () => {
    const before = await inboundCount(BOT_OUTCOME.OK);

    await adapterWithGaia().run({
      name: "ping",
      description: "ping",
      execute: async () => undefined,
    });

    expect(await inboundCount(BOT_OUTCOME.OK)).toBe(before + 1);
  });

  it("counts a command that throws as failed, not ok", async () => {
    const okBefore = await inboundCount(BOT_OUTCOME.OK);
    const failedBefore = await inboundCount(BOT_OUTCOME.FAILED);

    await adapterWithGaia().run({
      name: "boom",
      description: "boom",
      execute: async () => {
        throw new Error("upstream exploded");
      },
    });

    expect(await inboundCount(BOT_OUTCOME.FAILED)).toBe(failedBefore + 1);
    expect(await inboundCount(BOT_OUTCOME.OK)).toBe(okBefore);
  });
});
