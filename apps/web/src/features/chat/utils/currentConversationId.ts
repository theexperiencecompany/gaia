/**
 * The conversation id the browser is currently on, or undefined for a new chat.
 *
 * `useParams` can be stale: the chat route is replaced via `replaceState` when
 * the server mints a conversation, and Next's param snapshot does not always
 * follow. The pathname is the source of truth, so both the artifact-URL
 * resolver and the upload path read it through here — one implementation, not
 * two regexes that drift.
 */
export function currentConversationId(): string | undefined {
  if (globalThis.window === undefined) return undefined;
  const match = /\/(?:[a-z]{2}(?:-[A-Z]{2})?\/)?c\/([^/?#]+)/.exec(
    globalThis.window.location.pathname,
  );
  return match?.[1];
}
