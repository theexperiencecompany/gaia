import type { ActionEvent } from "@openuidev/react-lang";

/**
 * Dispatch an OpenUI ActionEvent to the appropriate handler.
 *
 * Strips both "action:" and "submit:" prefixes before routing.
 * Falls back to continue_conversation for unknown types.
 */
export async function dispatchOpenUIAction(
  event: ActionEvent,
  appendToInput: (text: string) => void,
): Promise<void> {
  const raw = event.type;

  // Normalize: strip "action:" or "submit:" prefix
  const type = raw.startsWith("action:")
    ? raw.slice("action:".length)
    : raw.startsWith("submit:")
      ? raw.slice("submit:".length)
      : raw;

  // continue_conversation — append message to chat input
  if (type === "continue_conversation") {
    appendToInput(event.humanFriendlyMessage);
    return;
  }

  // open_url — open in new tab
  if (type === "open_url") {
    const url = event.params?.url;
    if (typeof url === "string") {
      window.open(url, "_blank", "noopener,noreferrer");
    }
    return;
  }

  // cancel — noop dismiss button
  if (type === "cancel") {
    return;
  }

  // Fallback: unknown action — treat as continue_conversation
  console.warn(
    `[OpenUI] Unknown action type: "${type}". Falling back to continue_conversation.`,
  );
  appendToInput(event.humanFriendlyMessage);
}
