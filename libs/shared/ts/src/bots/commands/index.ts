/**
 * Unified bot command definitions.
 *
 * Each command is defined once here and consumed by all platform adapters.
 * The adapter's `registerCommands()` method maps these definitions to
 * platform-native command registration APIs.
 *
 * The `allCommands` array provides the full set for bulk registration
 * and for generating help text.
 *
 * @module
 */
export { authCommand } from "./auth";
export { conversationsCommand } from "./conversations";
export { gaiaCommand } from "./gaia";
export { helpCommand } from "./help";
export { newCommand } from "./new";
export { settingsCommand } from "./settings";
export { statusCommand } from "./status";
export { stopCommand } from "./stop";
export { todoCommand } from "./todo";
export { unlinkCommand } from "./unlink";
export { workflowCommand } from "./workflow";

import { authCommand } from "./auth";
import { conversationsCommand } from "./conversations";
import { gaiaCommand } from "./gaia";
import { helpCommand } from "./help";
import { newCommand } from "./new";
import { settingsCommand } from "./settings";
import { statusCommand } from "./status";
import { stopCommand } from "./stop";
import { todoCommand } from "./todo";
import { unlinkCommand } from "./unlink";
import { workflowCommand } from "./workflow";
import type { BotCommand } from "../types";

/**
 * All unified bot commands in registration order.
 *
 * Used by adapters to bulk-register commands and by `deploy-commands.ts`
 * to generate Discord slash command definitions.
 */
export const allCommands: BotCommand[] = [
  gaiaCommand,
  authCommand,
  statusCommand,
  helpCommand,
  settingsCommand,
  todoCommand,
  workflowCommand,
  conversationsCommand,
  newCommand,
  stopCommand,
  unlinkCommand,
];
