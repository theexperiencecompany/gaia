/**
 * Trigger Types - Re-exports all trigger type definitions.
 *
 * SCALABILITY NOTE:
 * TriggerConfig is defined as a flexible base type with index signature
 * to allow any trigger-specific properties. The backend validates the
 * specific fields for each trigger type.
 */

// Base types and interfaces
export type {
  BaseTriggerConfig,
  TriggerFieldSchema,
  TriggerSchema,
} from "./base";

// =============================================================================
// FLEXIBLE TRIGGER CONFIG TYPE
// =============================================================================

/**
 * Flexible trigger configuration type.
 *
 * Instead of a strict discriminated union, we use a base interface
 * with an index signature to allow any trigger-specific properties.
 * This enables:
 * - Adding new triggers without changing types
 * - Backend as source of truth for validation
 * - Spreading/merging config objects freely
 */
export interface TriggerConfig {
  type: string;
  enabled: boolean;
  // Allow any additional trigger-specific properties
  [key: string]: unknown;
}

/**
 * All possible trigger type literals.
 * These MUST match the backend TriggerType enum values.
 */
export type TriggerType = "manual" | "schedule" | "integration" | string; // Allow any string for new triggers

/**
 * Type guard to check if a string is a known trigger type.
 */
export const isKnownTriggerType = (type: string): type is TriggerType => {
  return ["manual", "schedule", "integration"].includes(type);
};

// =============================================================================
// HELPER TYPE GUARDS (for handler-specific logic)
// =============================================================================

/**
 * Check if trigger is an integration type (calendar, email, app, etc.).
 */
export const isIntegrationTrigger = (config: TriggerConfig): boolean => {
  return config.type === "integration";
};

/**
 * Check if trigger is schedule type.
 */
export const isScheduleTrigger = (config: TriggerConfig): boolean => {
  return config.type === "schedule";
};

/**
 * Check if trigger is manual type.
 */
export const isManualTrigger = (config: TriggerConfig): boolean => {
  return config.type === "manual";
};

// =============================================================================
// INTEGRATION TRIGGER TYPE
// =============================================================================

/**
 * Integration trigger configuration with required trigger_name.
 * This is the proper type for all Composio-based triggers.
 */
export interface IntegrationTriggerConfig extends TriggerConfig {
  type: "integration";
  trigger_name: string;
  trigger_data?: Record<string, unknown>;
  integration_id?: string;
  trigger_slug?: string;
  composio_trigger_ids?: string[];
}

/**
 * Type guard to check if an integration trigger has a valid trigger_name.
 * This should be used to validate that integration triggers are properly configured.
 */
export const hasValidTriggerName = (
  config: TriggerConfig,
): config is IntegrationTriggerConfig => {
  if (config.type !== "integration") return false;
  const triggerName = (config as IntegrationTriggerConfig).trigger_name;
  return typeof triggerName === "string" && triggerName.length > 0;
};
