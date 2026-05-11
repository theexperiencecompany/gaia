export interface PlatformLink {
  platform: "discord" | "slack" | "telegram" | "whatsapp";
  platformUserId: string;
  username?: string;
  displayName?: string;
  connectedAt?: string;
}
