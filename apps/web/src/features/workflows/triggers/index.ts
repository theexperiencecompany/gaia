/**
 * Triggers Module
 *
 * Centralized trigger management for workflows.
 * Backend is the single source of truth for trigger schemas.
 */

export {
  calendarTriggerHandler,
  gmailTriggerHandler,
  manualTriggerHandler,
  scheduleTriggerHandler,
} from "./handlers";
export { useTriggerSchemas } from "./hooks";
export {
  createDefaultTriggerConfig,
  getAllHandlers,
  getAllTriggerSlugs,
  getTriggerHandler,
  type RegisteredHandler,
  type TriggerDisplayInfo,
  type TriggerSettingsProps,
} from "./registry";
export * from "./types";
export {
  findTriggerSchema,
  getTriggerDisplayInfo,
  getTriggerEnabledIntegrations,
  normalizeTriggerSlug,
} from "./utils";
