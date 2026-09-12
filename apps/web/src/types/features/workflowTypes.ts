/**
 * SINGLE SOURCE OF TRUTH FOR ALL WORKFLOW, USE-CASE, AND COMMUNITY WORKFLOW TYPES
 *
 * This file contains all type definitions for:
 * - Workflows (user workflows, execution, metadata)
 * - Community Workflows (public shared workflows)
 * - Explore Workflows (featured/categorized workflows)
 * - Use Cases (landing page content, templates)
 *
 * DO NOT create duplicate type definitions elsewhere!
 */

import type { Schema } from "@shared/api/generated";
import type {
  TriggerConfig,
  TriggerConfigDraft,
  TriggerSchema,
} from "@/features/workflows/triggers/types";
import type { ContentCreator } from "@/types/shared/contentTypes";

// ============================================================================
// WORKFLOW STEP TYPES
// ============================================================================

/**
 * Simplified workflow step for community/public display
 * Used in CommunityWorkflow and UseCase types
 * Note: Backend actually returns full WorkflowStepType, but we type it as optional for flexibility
 */
export type PublicWorkflowStep = Schema<"PublicWorkflowStep">;

// ============================================================================
// WORKFLOW CONFIGURATION TYPES
// ============================================================================

// Re-export trigger types for convenience
// Re-export shared types that are identical between web and mobile
export type { TriggerConfig, TriggerConfigDraft, TriggerSchema };

// ============================================================================
// COMMUNITY & EXPLORE WORKFLOW TYPES
// ============================================================================

/**
 * Community workflow - publicly shared workflow
 * Also used for Explore workflows (featured workflows on landing/workflows pages)
 */
export type CommunityWorkflow = Schema<"PublicWorkflowCard">;

/**
 * Response type for community/explore workflows API
 */
export type CommunityWorkflowsResponse = Schema<"PublicWorkflowsResponse">;

// ============================================================================
// USE CASE TYPES (Landing Page Content & Templates)
// ============================================================================

/**
 * Use case - template/example workflow shown on landing pages
 * Can be converted from CommunityWorkflow for display
 */
export interface UseCase {
  title: string;
  description: string;
  detailed_description?: string;
  action_type: "prompt" | "workflow";
  /** User-chosen icon slug (gaia-icons component name) */
  icon?: string | null;
  /** Hex color for the user-chosen icon */
  icon_color?: string | null;
  system_workflow_key?: string | null;
  source_integration?: string | null;
  trigger_config?: TriggerConfig;
  integrations: string[]; // Tool category names
  categories: string[]; // Same as CommunityWorkflow categories
  published_id: string;
  slug: string;
  prompt?: string; // For prompt-type use cases and workflow execution context
  steps?: PublicWorkflowStep[]; // Workflow steps if action_type === "workflow"
  creator?: ContentCreator;
  total_executions?: number; // Run count for display
}

// ============================================================================
// MAIN WORKFLOW TYPES
// ============================================================================

/**
 * Legacy workflow data (for message components)
 */
export type WorkflowData = Schema<"SelectedWorkflowData-Output">;

/** Lightweight integration reference returned in workflow responses. */
export type IntegrationRef = Schema<"IntegrationRef">;

// Complete workflow entity
export type Workflow = Schema<"WorkflowWithIntegrations">;

// API request types
export type CreateWorkflowRequest = Schema<"CreateWorkflowRequest">;

export type WorkflowExecutionRequest = Schema<"WorkflowExecutionRequest">;

// API response types
export type WorkflowListResponse = Schema<"WorkflowListResponse">;

export type WorkflowResponse = Schema<"WorkflowResponse">;

export type WorkflowExecutionResponse = Schema<"WorkflowExecutionResponse">;
