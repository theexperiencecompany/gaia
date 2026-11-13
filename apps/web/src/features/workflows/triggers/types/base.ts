import type { WorkflowTriggerResponse } from "@shared/api/generated";
/**
 * Base trigger types and interfaces.
 *
 * Shared types used across all trigger implementations.
 */

// =============================================================================
// SCHEMA TYPES (from backend API)
// =============================================================================

/**
 * Complete trigger schema from backend API.
 * Fetched via /triggers/schema endpoint.
 */
export type TriggerSchema = WorkflowTriggerResponse;
