/**
 * Integration connection types for chat messages
 */

export interface IntegrationConnectionData {
  integration_id: string;
  integration_name: string;
  integration_description: string;
  integration_category: string;
  tool_name?: string;
  tool_category?: string;
  message: string;
  connect_url: string;
  settings_url: string;
}
