/**
 * Triggers Module
 *
 * Centralized trigger management for workflows.
 * Backend is the single source of truth for trigger schemas.
 */

export { useTriggerSchemas } from "./hooks";
export {
  createDefaultTriggerConfig,
  getTriggerHandler,
} from "./registry";
export * from "./types";
export { findTriggerSchema, getTriggerDisplayInfo } from "./utils";
