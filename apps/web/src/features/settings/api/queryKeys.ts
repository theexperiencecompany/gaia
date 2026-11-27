/** Canonical React Query keys for the self-host /setup endpoints. */
export const setupKeys = {
  /** Prefix — every /setup read. */
  all: ["setup"] as const,
  /** GET /setup/status. */
  status: ["setup", "status"] as const,
  /** GET /setup/catalog. */
  catalog: ["setup", "catalog"] as const,
  /** GET /setup/providers, the admin's masked stored credentials. */
  providers: ["setup", "providers"] as const,
  /** Prefix — GET /setup/composio and the toolkit catalog under it. */
  composio: ["setup", "composio"] as const,
  /** Prefix — the Composio toolkit catalog. */
  composioToolkits: ["setup", "composio", "toolkits"] as const,
  /** One searched page set of the toolkit catalog. */
  composioToolkitList: (query: string, category: string | null) =>
    ["setup", "composio", "toolkits", "list", query, category] as const,
  /** One toolkit's auth requirements. */
  composioToolkit: (slug: string | null) =>
    ["setup", "composio", "toolkits", "detail", slug] as const,
};

/** Canonical React Query keys for the user's own notification preferences and linked accounts. */
export const preferenceKeys = {
  /** GET /platform-links. */
  platformLinks: ["user", "platform-links"] as const,
  /** GET /notifications/preferences/channels. */
  channels: ["user", "notification-channels"] as const,
  /** GET /user/chat-channel-priority. */
  chatChannelPriority: ["user", "chat-channel-priority"] as const,
  /** GET /user/quiet-hours. */
  quietHours: ["user", "quiet-hours"] as const,
};
