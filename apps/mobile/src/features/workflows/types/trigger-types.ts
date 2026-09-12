import type { Schema } from "@gaia/shared/api/generated";
export type TriggerType = Schema<"TriggerType">;

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

export type TriggerConfig = Schema<"TriggerConfig">;

export interface TriggerSchemasResponse {
  schemas: TriggerSchema[];
}
