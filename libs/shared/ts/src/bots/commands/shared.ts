/**
 * Shared helpers for unified bot command execute functions.
 *
 * Extracted to eliminate duplicated patterns across command modules such as
 * `todo.ts` and `workflow.ts`. Each helper encapsulates a single recurring
 * concern so command modules stay focused on their own dispatch logic.
 *
 * @module
 */
import { truncateResponse, parseTextArgs } from "../utils";
import type { RichMessageTarget, PlatformName } from "../types";

/**
 * Resolves the active subcommand from structured args or raw text.
 *
 * Discord passes a structured `args.subcommand` string; text-based platforms
 * (Slack, Telegram) pass raw text that must be parsed. Falls back to `"list"`
 * when neither source provides a value.
 *
 * @param args - Parsed command arguments from the adapter.
 * @param rawText - Optional raw text input from text-based platforms.
 * @returns The resolved subcommand string.
 */
export function resolveSubcommand(
  args: Record<string, string | number | boolean | undefined>,
  rawText: string | undefined,
): string {
  return (
    (args.subcommand as string) ||
    (rawText ? parseTextArgs(rawText).subcommand : "list")
  );
}

/**
 * Truncates a response string to the platform limit and sends it as an
 * ephemeral message via the provided target.
 *
 * @param response - The response string to send.
 * @param target - The message target to reply on.
 */
export async function sendTruncated(
  response: string,
  target: RichMessageTarget & { platform: PlatformName },
): Promise<void> {
  const truncated = truncateResponse(response, target.platform);
  await target.sendEphemeral(truncated);
}
