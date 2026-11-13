/**
 * Where an X profile or post opens, the URLs the web cards build, and the
 * handle the way X writes it.
 *
 * @module
 */
import type { TwitterUserData } from "../../../chat/types";

const X_ORIGIN = "https://twitter.com";

export function xProfileUrl(username: string): string {
  return `${X_ORIGIN}/${username}`;
}

export function xPostUrl(username: string, postId: string): string {
  return `${X_ORIGIN}/${username}/status/${postId}`;
}

export function xHandle(username: string): string {
  return `@${username}`;
}

/** "Jane Doe (@jane)", how a card names an X account. */
export function xNameWithHandle(user: TwitterUserData): string {
  return `${user.name} (${xHandle(user.username)})`;
}
