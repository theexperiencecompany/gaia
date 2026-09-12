/**
 * Workflow Execution Types
 *
 * Types for workflow execution history tracking.
 */

import type { Schema } from "@shared/api/generated";

export type WorkflowExecution = Schema<"WorkflowExecution">;

export type WorkflowExecutionsResponse = Schema<"WorkflowExecutionsResponse">;
