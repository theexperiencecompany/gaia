/**
 * Integration connection types for chat messages
 */

export interface IntegrationConnectionData {
  integration_id: string;
  message: string;
}

export interface IntegrationInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  connected: boolean;
}

export interface IntegrationListData {
  integrations: IntegrationInfo[];
  total_count: number;
  connected_count: number;
}
