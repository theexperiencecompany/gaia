import type { PlatformIdentity, UserId } from "./types";

export type { AnalyticsId, PlatformIdentity, UserId } from "./types";

const OBJECT_ID = /^[0-9a-f]{24}$/;
const PLATFORM = /^[a-z][a-z0-9_]*$/;

/** Validate a Mongo ObjectId string as a UserId; throws on anything else. */
export function parseUserId(raw: string): UserId {
  if (!OBJECT_ID.test(raw)) {
    throw new TypeError(`UserId must be a Mongo ObjectId, got "${raw}"`);
  }
  return raw as UserId;
}

/** The distinct_id of a bot user who has not linked a GAIA account yet. */
export function platformIdentity(
  platform: string,
  platformUserId: string,
): PlatformIdentity {
  if (!PLATFORM.test(platform)) {
    throw new TypeError(
      `PlatformIdentity needs a platform slug, got "${platform}"`,
    );
  }
  if (!platformUserId.trim()) {
    throw new TypeError("PlatformIdentity needs a platform user id");
  }
  return `${platform}:${platformUserId}` as PlatformIdentity;
}
