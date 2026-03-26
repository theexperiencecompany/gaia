import type { InAppNotification } from "../types/inapp-notification-types";

/**
 * Returns an Expo Router path for the given in-app notification, or null if
 * no specific route can be determined. The caller is responsible for pushing
 * the route via `router.push`.
 *
 * Routing rules:
 *  - todo / task notifications  → /(app)/(tabs)/todos
 *  - workflow notifications      → /(app)/workflows/:id  (if id present in data)
 *  - chat / conversation notices → /(app)/(tabs)  (root conversation screen)
 *  - explicit redirect actions   → the redirect URL (if it starts with "/")
 */
export function getNotificationRoute(
  notification: InAppNotification,
): string | null {
  // 1. Check for an explicit redirect action first.
  const redirectAction = notification.content.actions?.find(
    (action) => action.type === "redirect" && action.config.redirect?.url,
  );
  if (redirectAction?.config.redirect?.url) {
    const url = redirectAction.config.redirect.url;
    if (url.startsWith("/")) {
      return url;
    }
  }

  // 2. Infer route from source / type strings.
  const key = (
    (notification.source ?? "") +
    " " +
    (notification.type ?? "")
  ).toLowerCase();

  if (key.includes("todo") || key.includes("task")) {
    return "/(app)/(tabs)/todos";
  }

  if (key.includes("workflow") || key.includes("automation")) {
    // Attempt to extract a workflow id from the notification metadata.
    const workflowId = extractWorkflowId(notification);
    if (workflowId) {
      return `/(app)/workflows/${workflowId}`;
    }
    return "/(app)/(tabs)";
  }

  if (
    key.includes("chat") ||
    key.includes("conversation") ||
    key.includes("message")
  ) {
    return "/(app)/(tabs)";
  }

  return null;
}

/**
 * Attempts to extract a workflow id from the notification's action configs or
 * redirect URLs. Returns null when no id can be determined.
 */
function extractWorkflowId(notification: InAppNotification): string | null {
  for (const action of notification.content.actions ?? []) {
    const redirectUrl = action.config.redirect?.url ?? "";
    const match = redirectUrl.match(/workflows\/([^/?#]+)/);
    if (match?.[1]) {
      return match[1];
    }
  }
  return null;
}
