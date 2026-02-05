/**
 * Workflow Form Schema
 *
 * Zod validation for workflow creation/edit form.
 *
 * SCALABILITY NOTE:
 * - Trigger configs use a flexible schema that validates base fields only
 * - Backend is the source of truth for trigger-specific validation
 * - New triggers can be added without changing this schema
 */

import { z } from "zod";

import type { Workflow } from "@/types/features/workflowTypes";

// =============================================================================
// TRIGGER CONFIG SCHEMAS
// =============================================================================

// Built-in triggers (schedule, manual) have strict schemas since they're frontend-controlled
const scheduleTriggerConfigSchema = z.object({
  type: z.literal("schedule"),
  enabled: z.boolean(),
  cron_expression: z.string().min(1, "Cron expression is required"),
  timezone: z.string().min(1),
  next_run: z.string().optional(),
});

const manualTriggerConfigSchema = z.object({
  type: z.literal("manual"),
  enabled: z.boolean(),
});

// Generic trigger config for all integration triggers (gmail, calendar, slack, etc.)
// Only validates base fields - backend validates trigger-specific fields
// This allows new triggers to be added without frontend schema changes
const integrationTriggerConfigSchema = z
  .object({
    type: z.string(),
    enabled: z.boolean(),
  })
  .passthrough(); // Allow any additional properties

// Combined trigger config - tries built-in first, then falls back to generic
const triggerConfigSchema = z.union([
  scheduleTriggerConfigSchema,
  manualTriggerConfigSchema,
  integrationTriggerConfigSchema,
]);

// =============================================================================
// MAIN FORM SCHEMA
// =============================================================================

export const workflowFormSchema = z.object({
  title: z.string().min(1, "Title is required").max(100, "Title too long"),
  description: z
    .string()
    .min(1, "Description is required")
    .max(2000, "Description too long"),
  activeTab: z.enum(["manual", "schedule", "trigger"]),
  selectedTrigger: z.string(),
  trigger_config: triggerConfigSchema,
});

// Export the inferred type
export type WorkflowFormData = z.infer<typeof workflowFormSchema>;

// =============================================================================
// HELPER FUNCTIONS
// =============================================================================

/**
 * Get default form values for new workflow creation.
 */
export const getDefaultFormValues = (): WorkflowFormData => ({
  title: "",
  description: "",
  activeTab: "schedule",
  selectedTrigger: "",
  trigger_config: {
    type: "schedule",
    enabled: true,
    cron_expression: "0 9 * * *", // Daily at 9 AM
    timezone: "UTC",
  },
});

/**
 * Convert existing workflow to form data for editing.
 * Works generically for any trigger type.
 */
export const workflowToFormData = (workflow: Workflow): WorkflowFormData => {
  const triggerType = workflow.trigger_config.type;

  // For integration triggers, try multiple locations for the specific trigger slug:
  // 1. trigger_name at top level (new format)
  // 2. trigger_data.trigger_name (properly structured format)
  // 3. type field itself (old format, where type contained the specific slug)
  const triggerName = (workflow.trigger_config as { trigger_name?: string })
    .trigger_name;
  const triggerDataName = (
    workflow.trigger_config as { trigger_data?: { trigger_name?: string } }
  ).trigger_data?.trigger_name;

  // Determine which tab should be active
  // Built-in triggers: schedule, manual -> their respective tabs
  // Everything else (gmail, calendar, slack, etc.) -> trigger tab
  const isBuiltInTrigger =
    triggerType === "schedule" || triggerType === "manual";
  const activeTab = isBuiltInTrigger
    ? (triggerType as "schedule" | "manual")
    : "trigger";

  // For integration triggers, selectedTrigger is the specific trigger slug.
  // Priority: trigger_name > trigger_data.trigger_name > type (for old format)
  // Note: For category-based types (calendar, email, app), we need the slug, not the category
  const isCategory = ["calendar", "email", "app"].includes(triggerType);
  const selectedTrigger = isBuiltInTrigger
    ? ""
    : triggerName || triggerDataName || (isCategory ? "" : triggerType);

  return {
    title: workflow.title,
    description: workflow.description,
    activeTab,
    selectedTrigger,
    trigger_config: workflow.trigger_config,
  };
};
