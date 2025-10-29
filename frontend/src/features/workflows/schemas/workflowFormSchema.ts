import { z } from "zod";

import type { Workflow } from "@/types/features/workflowTypes";

// Define the base trigger config schema
const baseTriggerConfigSchema = z.object({
  type: z.enum(["manual", "schedule", "email"]),
  enabled: z.boolean(),
});

// Define specific trigger configurations
const manualTriggerConfigSchema = baseTriggerConfigSchema.extend({
  type: z.literal("manual"),
});

const scheduleTriggerConfigSchema = baseTriggerConfigSchema.extend({
  type: z.literal("schedule"),
  cron_expression: z.string().min(1, "Cron expression is required"),
  timezone: z.string().min(1),
  next_run: z.string().optional(),
});

const emailTriggerConfigSchema = baseTriggerConfigSchema.extend({
  type: z.literal("email"),
});

// Union type for trigger config
const triggerConfigSchema = z.discriminatedUnion("type", [
  manualTriggerConfigSchema,
  scheduleTriggerConfigSchema,
  emailTriggerConfigSchema,
]);

// Main workflow form schema
export const workflowFormSchema = z.object({
  title: z.string().min(1, "Title is required").max(100, "Title too long"),
  description: z
    .string()
    .min(1, "Description is required")
    .max(500, "Description too long"),
  activeTab: z.enum(["manual", "schedule", "trigger"]),
  selectedTrigger: z.string(),
  trigger_config: triggerConfigSchema,
});

// Export the inferred type
export type WorkflowFormData = z.infer<typeof workflowFormSchema>;

// Helper function to get default form values
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

// Helper function to convert existing workflow to form data
export const workflowToFormData = (workflow: Workflow): WorkflowFormData => ({
  title: workflow.title,
  description: workflow.description,
  activeTab:
    workflow.trigger_config.type === "email"
      ? "trigger"
      : (workflow.trigger_config.type as "manual" | "schedule"),
  selectedTrigger: workflow.trigger_config.type === "email" ? "gmail" : "",
  trigger_config: workflow.trigger_config,
});
