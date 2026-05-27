/**
 * Base trigger types and interfaces.
 *
 * Shared types used across all trigger implementations.
 */

// =============================================================================
// SCHEMA TYPES (from backend API)
// =============================================================================

/**
 * Schema for a single trigger config field from backend.
 */
export interface TriggerFieldSchema {
  type: "string" | "integer" | "boolean" | "number";
  default: unknown;
  min?: number;
  max?: number;
  options_endpoint?: string;
  description?: string;
}

/**
 * Complete trigger schema from backend API.
 * Fetched via /triggers/schema endpoint.
 */
export interface TriggerSchema {
  slug: string;
  composio_slug: string;
  name: string;
  description: string;
  provider: string;
  integration_id: string;
  config_schema: Record<string, TriggerFieldSchema>;
}
