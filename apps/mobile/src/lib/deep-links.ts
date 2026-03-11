import * as Linking from "expo-linking";

export const DEEP_LINK_SCHEME = "gaia";

export const DEEP_LINK_PATHS = {
  chat: (conversationId: string) => `${DEEP_LINK_SCHEME}://chat/${conversationId}`,
  todos: () => `${DEEP_LINK_SCHEME}://todos`,
  todo: (todoId: string) => `${DEEP_LINK_SCHEME}://todos/${todoId}`,
  notifications: () => `${DEEP_LINK_SCHEME}://notifications`,
  settings: () => `${DEEP_LINK_SCHEME}://settings`,
  integrations: () => `${DEEP_LINK_SCHEME}://integrations`,
} as const;

export interface ParsedDeepLink {
  screen: "chat" | "todos" | "todo" | "notifications" | "settings" | "integrations" | "unknown";
  params: Record<string, string>;
}

export function parseDeepLink(url: string): ParsedDeepLink {
  const parsed = Linking.parse(url);
  const path = parsed.path ?? "";

  if (path.startsWith("chat/")) {
    const conversationId = path.replace("chat/", "");
    return { screen: "chat", params: { conversationId } };
  }

  if (path === "todos") {
    return { screen: "todos", params: {} };
  }

  if (path.startsWith("todos/")) {
    const todoId = path.replace("todos/", "");
    return { screen: "todo", params: { todoId } };
  }

  if (path === "notifications") {
    return { screen: "notifications", params: {} };
  }

  if (path === "settings") {
    return { screen: "settings", params: {} };
  }

  if (path === "integrations") {
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
