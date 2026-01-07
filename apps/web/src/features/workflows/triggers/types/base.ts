/**
 * Base trigger types and interfaces.
 *
 * Shared types used across all trigger implementations.
 */

import type { ComponentType } from "react";

// =============================================================================
// BASE CONFIG TYPES
// =============================================================================

/**
 * Base interface for all trigger configurations.
 */
export interface BaseTriggerConfig {
  type: string;
  enabled: boolean;
}

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

// =============================================================================
// HANDLER INTERFACES
// =============================================================================

/**
 * Props for trigger settings components.
 */
export interface TriggerSettingsProps<
  T extends BaseTriggerConfig = BaseTriggerConfig,
> {
  triggerConfig: T;
  onConfigChange: (config: T) => void;
}

/**
 * Display information for a trigger.
 */
export interface TriggerDisplayInfo {
  label: string;
  integrationId: string | null;
}

/**
 * Interface for trigger UI handlers.
 *
 * Each integration implements this interface to provide:
 * - Default config creation
 * - Optional settings UI component
 * - Display information
 */
export interface TriggerUIHandler<
  T extends BaseTriggerConfig = BaseTriggerConfig,
> {
  /** Trigger slugs this handler supports */
  triggerSlugs: string[];

  /** Create default trigger config for this type */
  createDefaultConfig: (slug: string, schema?: TriggerSchema) => T;

  /** Optional: Custom settings component for advanced configuration */
  SettingsComponent?: ComponentType<TriggerSettingsProps<T>>;

  /** Get display info (label, icon) for this trigger */
  getDisplayInfo: (config: T, schema?: TriggerSchema) => TriggerDisplayInfo;
}
