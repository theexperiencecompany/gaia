import type { ActionEvent } from "@openuidev/react-lang";

/**
 * Direct action handlers for OpenUI write-action components.
 * Each is implemented when its Phase 2 component is built.
 * Until then they warn and fall back to continue_conversation.
 */
type DirectActionHandler = (event: ActionEvent) => Promise<void>;

const DIRECT_HANDLERS: Record<string, DirectActionHandler> = {
  send_email: async (event) => {
    console.warn("[OpenUI] send_email handler not yet implemented", event);
  },
  delete_calendar_event: async (event) => {
    console.warn(
      "[OpenUI] delete_calendar_event handler not yet implemented",
      event,
    );
  },
  edit_calendar_event: async (event) => {
    console.warn(
      "[OpenUI] edit_calendar_event handler not yet implemented",
      event,
    );
  },
  create_calendar_event: async (event) => {
    console.warn(
      "[OpenUI] create_calendar_event handler not yet implemented",
      event,
    );
  },
  connect_integration: async (event) => {
    console.warn(
      "[OpenUI] connect_integration handler not yet implemented",
      event,
    );
  },
  create_todo: async (event) => {
    console.warn("[OpenUI] create_todo handler not yet implemented", event);
  },
  delete_todo: async (event) => {
    console.warn("[OpenUI] delete_todo handler not yet implemented", event);
  },
  complete_todo: async (event) => {
    console.warn("[OpenUI] complete_todo handler not yet implemented", event);
  },
};

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
    if (event.humanFriendlyMessage) {
      appendToInput(event.humanFriendlyMessage);
    }
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

  const handler = DIRECT_HANDLERS[type];
  if (handler) {
    await handler(event);
    return;
  }

  // Fallback: unknown action — treat as continue_conversation
  console.warn(
    `[OpenUI] Unknown action type: "${type}". Falling back to continue_conversation.`,
  );
  if (event.humanFriendlyMessage) {
    appendToInput(event.humanFriendlyMessage);
  }
}
