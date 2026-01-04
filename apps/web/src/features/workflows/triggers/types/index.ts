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
 * This is informational - actual validation happens on backend.
 */
export type TriggerType =
  | "email"
  | "calendar_event_created"
  | "calendar_event_starting_soon"
  | "schedule"
  | "manual"
  | string; // Allow any string for new triggers

/**
 * Type guard to check if a string is a known trigger type.
 */
export const isKnownTriggerType = (type: string): type is TriggerType => {
  return [
    "email",
    "calendar_event_created",
    "calendar_event_starting_soon",
    "schedule",
    "manual",
  ].includes(type);
};

// =============================================================================
// HELPER TYPE GUARDS (for handler-specific logic)
// =============================================================================

/**
 * Check if trigger is a calendar type (for calendar handler).
 */
export const isCalendarTrigger = (config: TriggerConfig): boolean => {
  return (
    config.type === "calendar_event_created" ||
    config.type === "calendar_event_starting_soon"
  );
};

/**
 * Check if trigger is email type.
 */
export const isEmailTrigger = (config: TriggerConfig): boolean => {
  return config.type === "email";
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
