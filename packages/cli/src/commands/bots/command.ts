// `gaia bots` — run GAIA's Telegram, Discord and Slack bots on a self-host
// install with your own bot tokens.

import { Argument, Command } from "commander";
import { CLI_COMMAND_DESCRIPTIONS } from "../../../../../libs/shared/ts/src/cli/command-manifest.js";
import { SELFHOST_BOTS, type SelfhostBot } from "../../lib/bots.js";
import { runAction } from "../../lib/command-action.js";
import { printHeader } from "../../ui/header/header-lines.js";
import {
  type BotCredentials,
  runBotsAdd,
  runBotsList,
  runBotsRemove,
} from "./handler.js";

function platformArgument(): Argument {
  return new Argument("<platform>", "chat platform").choices(SELFHOST_BOTS);
}

export const botsCommand = new Command("bots")
  .description(CLI_COMMAND_DESCRIPTIONS.bots)
  .hook("preAction", () => printHeader())
  .addHelpText(
    "after",
    `
Examples:
  gaia bots add telegram          (asks for the token from @BotFather)
  gaia bots add telegram --token <token from @BotFather>
  gaia bots add discord --token <bot token>
  gaia bots add slack --token xoxb-... --app-token xapp-... --signing-secret <secret>
`,
  );

botsCommand
  .command("add")
  .description(
    "Check the bot's credentials (asked for when not passed), save them and start the bot",
  )
  .addArgument(platformArgument())
  .option("--token <token>", "Bot token (Slack: the xoxb- bot user token)")
  .option("--app-token <token>", "Slack: app-level token (xapp-)")
  .option("--signing-secret <secret>", "Slack: the app's signing secret")
  .action(async (platform: SelfhostBot, options: BotCredentials) => {
    await runAction(() => runBotsAdd(platform, options));
  });

botsCommand
  .command("list")
  .alias("ls")
  .description("Show the enabled bots and whether each is running")
  .action(async () => {
    await runAction(runBotsList);
  });

botsCommand
  .command("remove")
  .alias("rm")
  .description("Stop a bot and delete its saved credentials")
  .addArgument(platformArgument())
  .action(async (platform: SelfhostBot) => {
    await runAction(() => runBotsRemove(platform));
  });
