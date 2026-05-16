/* biome-ignore-all lint/performance/noReExportAll: barrel file — package public API */
/**
 * Bot utility barrel export.
 *
 * Three layers of reusable logic, ordered from low-level to high-level:
 *
 * 1. formatters - Pure functions that turn data into display strings.
 *    Use these when you need custom response assembly.
 *
 * 2. commands  - Business-logic handlers that call GaiaClient, format results,
 *    and return a ready-to-send string. Bot adapters call these directly.
 *
 * 3. streaming - handleStreamingChat: full streaming lifecycle handler.
 *    Bot adapters provide three callbacks (editMessage, onAuthError, onGenericError)
 *    and the shared function handles throttling, cursor display, and error routing.
 *
 * Response sizing (truncate/chunk + platform character limits) lives in
 * ./response so streaming.ts can depend on it without creating a cycle
 * back through this barrel.
 */

export * from "./commands";
export * from "./formatters";
export * from "./logger";
export * from "./response";
export * from "./streaming";

/**
 * Parses whitespace-separated text into a subcommand and remaining args.
 * Used by Slack and Telegram command handlers where input is plain text.
 *
 * @param text - Raw command text.
 * @param skipFirst - If true, skips the first token (e.g. for Telegram where the command name is included).
 * @returns The parsed subcommand (defaults to "list") and remaining args.
 */
export function parseTextArgs(
  text: string,
  skipFirst = false,
): { subcommand: string; args: string[] } {
  const parts = text.trim().split(/\s+/);
  const tokens = skipFirst ? parts.slice(1) : parts;
  return { subcommand: tokens[0] || "list", args: tokens.slice(1) };
}
