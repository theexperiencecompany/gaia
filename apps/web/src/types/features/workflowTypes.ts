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

import type {
  EmailTriggerConfig,
  ManualTriggerConfig,
  ScheduleTriggerConfig,
  TriggerConfig,
} from "@/config/registries/triggerRegistry";
import type { ContentCreator } from "@/types/shared/contentTypes";

// ============================================================================
// WORKFLOW STEP TYPES
// ============================================================================

/**
 * Legacy workflow step data (for message components and chat history)
 */
export interface WorkflowStepData {
  id: string;
  title: string;
  description: string;
  category: string;
  inputs?: Record<string, unknown>;
  order?: number;
}

/**
 * Complete workflow step type for API operations and execution
 */
export interface WorkflowStepType {
  id: string;
  title: string;
  category: string;
  description: string;
  inputs: Record<string, unknown>;
  order: number;
  executed_at?: string;
  result?: Record<string, unknown>;
}

/**
 * Simplified workflow step for community/public display
 * Used in CommunityWorkflow and UseCase types
 * Note: Backend actually returns full WorkflowStepType, but we type it as optional for flexibility
 */
export interface PublicWorkflowStep {
  id?: string;
  title: string;
  category: string;
  description: string;
  inputs?: Record<string, unknown>;
  order?: number;
}

// ============================================================================
// WORKFLOW CONFIGURATION TYPES
// ============================================================================

// Re-export trigger types for convenience
export type {
  EmailTriggerConfig,
  ManualTriggerConfig,
  ScheduleTriggerConfig,
  TriggerConfig,
};

/**
 * Execution configuration for workflows
 */
export interface ExecutionConfig {
  method: "chat" | "background" | "hybrid";
  timeout_seconds: number;
  max_retries: number;
  retry_delay_seconds: number;
  notify_on_completion: boolean;
  notify_on_failure: boolean;
}

/**
 * Workflow metadata tracking
 */
export interface WorkflowMetadata {
  created_from: "chat" | "modal" | "todo" | "template" | "api";
  template_id?: string;
  related_todo_id?: string;
  related_conversation_id?: string;
  tags: string[];
  category?: string;
  total_executions: number;
  successful_executions: number;
  last_execution_at?: string;
  average_execution_time?: number;
}

// ============================================================================
// COMMUNITY & EXPLORE WORKFLOW TYPES
// ============================================================================

/**
 * Community workflow - publicly shared workflow
 * Also used for Explore workflows (featured workflows on landing/workflows pages)
 */
export interface CommunityWorkflow {
  id: string;
  title: string;
  description: string;
  steps: PublicWorkflowStep[];
  created_at: string;
  creator: ContentCreator;
  categories?: string[]; // For filtering (Students, Founders, Engineering, etc.)
  total_executions?: number; // Run count for display
}

/**
 * Response type for community/explore workflows API
 */
export interface CommunityWorkflowsResponse {
  workflows: CommunityWorkflow[];
  total: number;
}

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
  integrations: string[]; // Tool category names
  categories: string[]; // Same as CommunityWorkflow categories
  published_id: string;
  slug: string;
  prompt?: string; // For prompt-type use cases
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
export interface WorkflowData {
  id: string;
  title: string;
  description: string;
  steps: WorkflowStepData[];
}

// Complete workflow entity
export interface Workflow {
  id: string;
  title: string;
  description: string;
  steps: WorkflowStepType[];
  trigger_config: TriggerConfig;
  execution_config: ExecutionConfig;
  metadata: WorkflowMetadata;
  activated: boolean;
  user_id: string;
  created_at: string;
  updated_at: string;
  last_executed_at?: string;
  current_step_index: number;
  execution_logs: string[];
  error_message?: string;

  // Execution statistics
  total_executions: number;
  successful_executions: number;

  // Community features
  is_public?: boolean;
  created_by?: string;
  creator?: ContentCreator; // Optional creator info from community workflows
}

// API request types
export interface CreateWorkflowRequest {
  title: string;
  description: string;
  trigger_config: TriggerConfig;
  steps?: WorkflowStepData[]; // Optional: pre-existing steps from explore/community workflows
  execution_config?: ExecutionConfig;
  metadata?: Partial<WorkflowMetadata>;
  generate_immediately?: boolean;
}

export interface WorkflowExecutionRequest {
  execution_method?: "chat" | "background" | "hybrid";
  context?: Record<string, unknown>;
}

// API response types
export interface WorkflowStatusResponse {
  workflow_id: string;
  activated: boolean;
  current_step_index: number;
  total_steps: number;
  progress_percentage: number;
  last_updated: string;
  error_message?: string;
  logs: string[];
}

export interface WorkflowListResponse {
  workflows: Workflow[];
  total_count: number;
  page: number;
  page_size: number;
}

export interface WorkflowResponse {
  workflow: Workflow;
  message: string;
}

export interface WorkflowExecutionResponse {
  execution_id: string;
  message: string;
  estimated_completion_time?: string;
}
