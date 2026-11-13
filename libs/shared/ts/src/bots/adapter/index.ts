/**
 * Bot adapter layer.
 *
 * Provides the {@link BaseBotAdapter} abstract class that all platform bots
 * extend.
 *
 * @module
 */
export { BaseBotAdapter, type OutboundFile } from "./base";
export { BotServer } from "./base-server";
export { runBotProcess } from "./process-lifecycle";
