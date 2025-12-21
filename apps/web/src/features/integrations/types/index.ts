/**
 * Integration system types and interfaces
 */

export interface Integration {
  id: string;
  name: string;
  description: string;
  category: "productivity" | "communication" | "developer" | "social";
  status: "connected" | "not_connected" | "error";
  loginEndpoint?: string;
  disconnectEndpoint?: string;
  settingsPath?: string;
  // New properties for unified integrations
  isSpecial?: boolean;
  displayPriority?: number;
  includedIntegrations?: string[];
  isFeatured?: boolean;
}

export interface IntegrationStatus {
  integrationId: string;
  connected: boolean;
  lastConnected?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

export interface IntegrationCategory {
  id: string;
  name: string;
  description: string;
  integrations: Integration[];
}

export type IntegrationAction =
  | "connect"
  | "disconnect"
  | "settings"
  | "refresh";

export interface IntegrationActionEvent {
  integration: Integration;
  action: IntegrationAction;
}
