export type TriggerType = "manual" | "schedule" | string;

export interface TriggerSchema {
  slug: string;
  composio_slug: string;
  name: string;
  description: string;
  provider: string;
  integration_id: string;
  config_schema: Record<string, TriggerFieldSchema>;
}

export interface TriggerFieldSchema {
  type: "string" | "integer" | "boolean" | "number";
  default: unknown;
  min?: number;
  max?: number;
  options_endpoint?: string;
  description?: string;
}

export interface TriggerConfig {
  type: string;
  enabled: boolean;
  [key: string]: unknown;
}

export interface TriggerSchemasResponse {
  schemas: TriggerSchema[];
}
