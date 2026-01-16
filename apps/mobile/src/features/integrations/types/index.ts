export interface Integration {
  id: string;
  name: string;
  description: string;
  category: "productivity" | "communication" | "social";
  provider: string;
  available: boolean;
  loginEndpoint: string;
  isSpecial: boolean;
  displayPriority: number;
  includedIntegrations: string[];
  isFeatured: boolean;
}

export interface IntegrationsConfigResponse {
  integrations: Integration[];
}

export interface IntegrationStatus {
  integrationId: string;
  connected: boolean;
}

export interface IntegrationsStatusResponse {
  integrations: IntegrationStatus[];
}

export interface IntegrationWithStatus extends Integration {
  connected: boolean;
  logo: string;
}
