/**
 * Bot adapter layer.
 *
 * Provides the {@link BaseBotAdapter} abstract class that all platform bots
 * extend, plus the {@link richMessageToMarkdown} utility for platforms
 * without native rich-embed support.
 *
 * @module
 */
export { BaseBotAdapter } from "./base";
export { richMessageToMarkdown } from "./rich-renderer";
