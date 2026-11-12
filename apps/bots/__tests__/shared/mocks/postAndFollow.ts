/**
 * The spy behind the mocked BaseBotAdapter's postAndFollow: adapter tests assert
 * the request, the conversation surface and the auth handler an adapter hands it.
 */
import { vi } from "vitest";
import type {
  ChatRequest,
  ConversationSurface,
} from "../../../../../libs/shared/ts/src/bots";

export const postAndFollowSpy =
  vi.fn<
    (
      request: ChatRequest,
      surface: ConversationSurface,
      onAuthError: (authUrl: string) => Promise<void>,
    ) => Promise<void>
  >();

/** The surface the adapter handed to its newest postAndFollow call. */
export function lastSurface(): ConversationSurface {
  const call = postAndFollowSpy.mock.calls.at(-1);
  if (!call) throw new Error("postAndFollow was not called");
  return call[1];
}

/** The auth handler the adapter handed to its newest postAndFollow call. */
export function lastAuthHandler(): (authUrl: string) => Promise<void> {
  const call = postAndFollowSpy.mock.calls.at(-1);
  if (!call) throw new Error("postAndFollow was not called");
  return call[2];
}
