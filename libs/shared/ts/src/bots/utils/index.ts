const LIMITS: Record<string, number> = {
  discord: 2000,
  slack: 4000,
  telegram: 4096,
};

/**
 * Truncates a response message to fit within the platform's character limit.
 *
 * @param text - The message text to truncate.
 * @param platform - The target platform (discord, slack, telegram).
 * @returns The truncated message, appended with "..." if truncated.
 */
export function truncateResponse(
  text: string,
  platform: "discord" | "slack" | "telegram",
): string {
  const limit = LIMITS[platform];
  if (text.length <= limit) {
    return text;
  }
  return text.slice(0, limit - 3) + "...";
}

/**
 * Formats an error into a user-friendly string message.
 *
 * @param error - The error object or unknown value.
 * @returns A formatted error message string.
 */
export function formatError(error: unknown): string {
  if (error instanceof Error) {
    return `An error occurred: ${error.message}`;
  }
  return "An unexpected error occurred. Please try again.";
}
