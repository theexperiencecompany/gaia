/**
 * Trigger Handler Registry
 *
 * Maps trigger slugs to their UI handlers.
 * Provides lookup functions for finding handlers by slug.
 *
 * SCALABILITY:
 * - Handlers are registered once at import time
 * - O(1) lookup by slug
 * - New handlers can be added by creating a handler file and registering here
 */

import type { ComponentType } from "react";
import {
  calendarTriggerHandler,
  gmailTriggerHandler,
  manualTriggerHandler,
  scheduleTriggerHandler,
} from "./handlers";
import type { TriggerConfig, TriggerSchema } from "./types";

// =============================================================================
// HANDLER INTERFACE (simplified for scalability)
// =============================================================================

/**
 * Display info returned by handlers.
 */
export interface TriggerDisplayInfo {
  label: string;
  integrationId: string | null;
}

/**
 * Props for trigger settings components.
 * Uses generic TriggerConfig to avoid type-specific coupling.
 */
export interface TriggerSettingsProps {
  triggerConfig: TriggerConfig;
  onConfigChange: (config: TriggerConfig) => void;
}

/**
 * Simplified handler interface for the registry.
 * Uses TriggerConfig directly to avoid complex generics.
 */
export interface RegisteredHandler {
  /** Trigger slugs this handler supports */
  triggerSlugs: string[];

  /** Create default trigger config for this type */
  createDefaultConfig: (slug: string, schema?: TriggerSchema) => TriggerConfig;

  /** Optional: Custom settings component for advanced configuration */
  SettingsComponent?: ComponentType<TriggerSettingsProps>;

  /** Get display info (label, integrationId) for this trigger */
  getDisplayInfo: (
    config: TriggerConfig,
    schema?: TriggerSchema,
  ) => TriggerDisplayInfo;
}

// =============================================================================
// REGISTRY
// =============================================================================

/**
 * All registered trigger handlers.
 * To add a new trigger:
 * 1. Create handler file in handlers/
 * 2. Add to this array
 */
const handlers: RegisteredHandler[] = [
  calendarTriggerHandler,
  gmailTriggerHandler,
  scheduleTriggerHandler,
  manualTriggerHandler,
];

/**
 * Map of slug -> handler for efficient lookup.
 */
const slugToHandler = new Map<string, RegisteredHandler>();

// Build the lookup map
for (const handler of handlers) {
  for (const slug of handler.triggerSlugs) {
    slugToHandler.set(slug, handler);
  }
}

// =============================================================================
// LOOKUP FUNCTIONS
// =============================================================================

/**
 * Get a trigger handler by its slug.
 *
 * @param slug - The trigger slug (e.g., "gmail_new_message", "calendar_event_created")
 * @returns The handler or undefined if not found
 */
export function getTriggerHandler(slug: string): RegisteredHandler | undefined {
  return slugToHandler.get(slug);
}

/**
 * Get all registered trigger handlers.
 */
export function getAllHandlers(): RegisteredHandler[] {
  return handlers;
}

/**
 * Get all registered trigger slugs.
 */
export function getAllTriggerSlugs(): string[] {
  return Array.from(slugToHandler.keys());
}

/**
 * Create default config for a trigger slug.
 *
 * @param slug - The trigger slug
 * @returns Default config or undefined if handler not found
 */
export function createDefaultTriggerConfig(
  slug: string,
): TriggerConfig | undefined {
  const handler = getTriggerHandler(slug);
  if (!handler) return undefined;
  return handler.createDefaultConfig(slug);
}
