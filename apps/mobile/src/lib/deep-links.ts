import * as Linking from "expo-linking";

export const DEEP_LINK_SCHEME = "gaia";

export const DEEP_LINK_PATHS = {
  chat: (conversationId: string) =>
    `${DEEP_LINK_SCHEME}://chat/${conversationId}`,
  todos: () => `${DEEP_LINK_SCHEME}://todos`,
  todo: (todoId: string) => `${DEEP_LINK_SCHEME}://todos/${todoId}`,
  notifications: () => `${DEEP_LINK_SCHEME}://notifications`,
  settings: () => `${DEEP_LINK_SCHEME}://settings`,
  integrations: () => `${DEEP_LINK_SCHEME}://integrations`,
} as const;

export interface ParsedDeepLink {
  screen:
    | "chat"
    | "todos"
    | "todo"
    | "notifications"
    | "settings"
    | "integrations"
    | "unknown";
  params: Record<string, string>;
}

export function parseDeepLink(url: string): ParsedDeepLink {
  const parsed = Linking.parse(url);
  // For gaia://chat/123, expo-linking gives: host="chat", path="123"
  // For gaia://todos,    expo-linking gives: host="todos", path=null
  const host = parsed.hostname ?? "";
  const path = parsed.path ?? "";

  if (host === "chat") {
    const conversationId = path.replace(/^\//, "");
    return conversationId
      ? { screen: "chat", params: { conversationId } }
      : { screen: "unknown", params: {} };
  }

  if (host === "todos") {
    const todoId = path.replace(/^\//, "");
    return todoId
      ? { screen: "todo", params: { todoId } }
      : { screen: "todos", params: {} };
  }

  if (host === "notifications") {
    return { screen: "notifications", params: {} };
  }

  if (host === "settings") {
    return { screen: "settings", params: {} };
  }

  if (host === "integrations") {
    return { screen: "integrations", params: {} };
  }

  return { screen: "unknown", params: {} };
}

export function getRouteForDeepLink(link: ParsedDeepLink): string | null {
  switch (link.screen) {
    case "chat":
      return link.params.conversationId
        ? `/(app)/c/${link.params.conversationId}`
        : null;
    case "todos":
      return "/(app)/todos";
    case "todo":
      return link.params.todoId
        ? `/(app)/todos?todoId=${link.params.todoId}`
        : "/(app)/todos";
    case "notifications":
      return "/(app)/notifications";
    case "settings":
      return "/(app)/settings";
    case "integrations":
      return "/(app)/integrations";
    default:
      return null;
  }
}
