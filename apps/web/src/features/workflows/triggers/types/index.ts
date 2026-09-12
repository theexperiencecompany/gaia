/**
 * Trigger Types - Re-exports all trigger type definitions.
 *
 * SCALABILITY NOTE:
 * TriggerConfig is defined as a flexible base type with index signature
 * to allow any trigger-specific properties. The backend validates the
 * specific fields for each trigger type.
 */

// Base types and interfaces
import type { Schema } from "@shared/api/generated";

export type { TriggerSchema } from "./base";

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
export type TriggerConfig = Schema<"TriggerConfig">;
/**
 * The editor's in-progress trigger config. `trigger_data` is the provider's
 * fields with `trigger_name` still a plain slug string — the discriminated
 * union the API validates only holds once the user has finished picking.
 */
export type TriggerConfigDraft = Omit<
  TriggerConfig,
  "type" | "trigger_data"
> & {
  type: string;
  trigger_data?: ({ trigger_name: string } & Record<string, unknown>) | null;
} & Record<string, unknown>;

/** The one boundary between the editor's draft and the wire: the API validates it. */
export const toTriggerConfig = (draft: TriggerConfigDraft): TriggerConfig =>
  draft as TriggerConfig;

// =============================================================================
// HELPER TYPE GUARDS (for handler-specific logic)
// =============================================================================

/**
 * Check if trigger is an integration type (calendar, email, app, etc.).
 */
export const isIntegrationTrigger = (config: TriggerConfigDraft): boolean => {
  return config.type === "integration";
};

// =============================================================================
// INTEGRATION TRIGGER TYPE
// =============================================================================

/**
 * Integration trigger configuration with required trigger_name.
 * This is the proper type for all Composio-based triggers.
 */
export interface IntegrationTriggerConfig extends TriggerConfigDraft {
  type: "integration";
  trigger_name: string;
  integration_id?: string;
  trigger_slug?: string;
}

/**
 * Type guard to check if an integration trigger has a valid trigger_name.
 * This should be used to validate that integration triggers are properly configured.
 */
export const hasValidTriggerName = (
  config: TriggerConfigDraft,
): config is IntegrationTriggerConfig => {
  if (config.type !== "integration") return false;
  const triggerName = (config as IntegrationTriggerConfig).trigger_name;
  return typeof triggerName === "string" && triggerName.length > 0;
};
