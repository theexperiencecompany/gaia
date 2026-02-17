const LIMITS: Record<string, number> = {
  discord: 2000,
  slack: 4000,
  telegram: 4096,
};

/**
 * Splits a message into platform-safe chunks, preserving markdown code blocks.
 */
export function splitMessage(
  text: string,
  platform: "discord" | "slack" | "telegram",
): string[] {
  if (!text.trim()) {
    return ["No response was generated. Please try again."];
  }

  const limit = LIMITS[platform];
  if (text.length <= limit) {
    return [text];
  }

  const chunks: string[] = [];
  let remaining = text;

  while (remaining.length > 0) {
    if (remaining.length <= limit) {
      chunks.push(remaining);
      break;
    }

    let splitAt = -1;

    // Try double newline
    const doubleNl = remaining.lastIndexOf("\n\n", limit);
    if (doubleNl > limit * 0.3) {
      splitAt = doubleNl;
    }

    // Try single newline
    if (splitAt === -1) {
      const singleNl = remaining.lastIndexOf("\n", limit);
      if (singleNl > limit * 0.3) {
        splitAt = singleNl;
      }
    }

    // Try space
    if (splitAt === -1) {
      const space = remaining.lastIndexOf(" ", limit);
      if (space > limit * 0.3) {
        splitAt = space;
      }
    }

    // Hard cut as last resort
    if (splitAt === -1) {
      splitAt = limit;
    }

    let chunk = remaining.slice(0, splitAt);
    remaining = remaining.slice(splitAt).trimStart();

    // Handle unclosed code blocks
    const fenceCount = (chunk.match(/```/g) || []).length;
    if (fenceCount % 2 !== 0) {
      chunk += "\n```";
      remaining = "```\n" + remaining;
    }

    chunks.push(chunk);
  }

  return chunks;
}

/**
 * @deprecated Use splitMessage instead.
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
 */
export function formatError(error: unknown): string {
  if (error instanceof Error) {
    return `An error occurred: ${error.message}`;
  }
  return "An unexpected error occurred. Please try again.";
}

/**
 * In-memory sliding window rate limiter for bot users.
 */
export class UserRateLimiter {
  private windows: Map<string, number[]> = new Map();
  private maxRequests: number;
  private windowMs: number;

  constructor(maxRequests = 20, windowMs = 60_000) {
    this.maxRequests = maxRequests;
    this.windowMs = windowMs;
  }

  check(userId: string): boolean {
    const now = Date.now();
    const cutoff = now - this.windowMs;

    let timestamps = this.windows.get(userId);
    if (!timestamps) {
      timestamps = [];
      this.windows.set(userId, timestamps);
    }

    // Remove expired entries
    while (timestamps.length > 0 && timestamps[0] <= cutoff) {
      timestamps.shift();
    }

    if (timestamps.length >= this.maxRequests) {
      return false;
    }

    timestamps.push(now);
    return true;
  }
}
