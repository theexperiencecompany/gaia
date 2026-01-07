/**
 * Triggers Module
 *
 * Centralized trigger management for workflows.
 * Backend is the single source of truth for trigger schemas.
 *
 * ADDING NEW TRIGGERS:
 * 1. Create a handler file in handlers/ (see gmail.tsx for simple example)
 * 2. Register the handler in registry.ts
 * 3. Done! The new trigger will work automatically.
 */

// Handlers (if direct access needed)
export {
  calendarTriggerHandler,
  gmailTriggerHandler,
  manualTriggerHandler,
  scheduleTriggerHandler,
} from "./handlers";
// Hooks
export { useTriggerSchemas } from "./hooks";
// Registry (handlers and lookup functions)
export {
  createDefaultTriggerConfig,
  getAllHandlers,
  getAllTriggerSlugs,
  getTriggerHandler,
  type RegisteredHandler,
  type TriggerDisplayInfo,
  type TriggerSettingsProps,
} from "./registry";
// Types
export * from "./types";

// Utils
export { getTriggerDisplayInfo, getTriggerEnabledIntegrations } from "./utils";
