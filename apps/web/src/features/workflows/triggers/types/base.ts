import type { Schema } from "@shared/api/generated";
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
export type TriggerFieldSchema = Schema<"TriggerConfigFieldSchema">;

/**
 * Complete trigger schema from backend API.
 * Fetched via /triggers/schema endpoint.
 */
export type TriggerSchema = Schema<"WorkflowTriggerResponse">;
