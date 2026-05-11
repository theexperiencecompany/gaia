/**
 * Minimal structural type for @openuidev/react-lang's ActionEvent.
 * Duck-typed to avoid a hard dep on a specific openui version.
 */
export interface OpenUIActionEventLike {
  type: string;
  humanFriendlyMessage: string;
  params?: Record<string, unknown>;
}

export interface OpenUIActionHandlers {
  appendToInput: (text: string) => void;
  openUrl: (url: string) => void;
}

/**
 * Dispatch an OpenUI ActionEvent to platform-specific handlers.
 *
 * Strips both "action:" and "submit:" prefixes before routing.
 * Falls back to continue_conversation for unknown types.
 */
export async function dispatchOpenUIAction(
  event: OpenUIActionEventLike,
  handlers: OpenUIActionHandlers,
): Promise<void> {
  const raw = event.type;

  const type = raw.startsWith("action:")
    ? raw.slice("action:".length)
    : raw.startsWith("submit:")
      ? raw.slice("submit:".length)
      : raw;

  if (type === "continue_conversation") {
    handlers.appendToInput(event.humanFriendlyMessage);
    return;
  }

  if (type === "open_url") {
    const url = event.params?.url;
    if (typeof url === "string") {
      handlers.openUrl(url);
    }
    return;
  }

  if (type === "cancel") {
    return;
  }

  console.warn(
    `[OpenUI] Unknown action type: "${type}". Falling back to continue_conversation.`,
  );
  handlers.appendToInput(event.humanFriendlyMessage);
}
