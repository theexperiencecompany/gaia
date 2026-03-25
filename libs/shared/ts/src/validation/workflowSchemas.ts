import { z } from "zod";

export const workflowStepSchema = z.object({
  title: z.string().min(1, "Step title is required").max(200),
  category: z.string().min(1).max(100),
  description: z.string().max(1000).optional().default(""),
  order: z.number().int().nonnegative().optional(),
});

export const triggerConfigSchema = z
  .object({
    type: z.string().min(1, "Trigger type is required"),
    enabled: z.boolean().default(true),
    cron_expression: z.string().optional(),
    timezone: z.string().optional(),
  })
  .passthrough();

export const createWorkflowSchema = z.object({
  name: z
    .string()
    .min(1, "Name is required")
    .max(100, "Name must be 100 characters or fewer"),
  description: z
    .string()
    .max(300, "Description must be 300 characters or fewer")
    .optional(),
  prompt: z
    .string()
    .min(1, "Prompt is required")
    .max(5000, "Prompt must be 5000 characters or fewer"),
  trigger: triggerConfigSchema,
  steps: z.array(workflowStepSchema).min(0).default([]),
});

export const updateWorkflowSchema = z.object({
  name: z.string().min(1).max(100).optional(),
  description: z.string().max(300).optional(),
  prompt: z.string().min(1).max(5000).optional(),
  trigger: triggerConfigSchema.optional(),
  steps: z.array(workflowStepSchema).optional(),
  activated: z.boolean().optional(),
});

export type CreateWorkflowInput = z.infer<typeof createWorkflowSchema>;
export type UpdateWorkflowInput = z.infer<typeof updateWorkflowSchema>;
export type WorkflowStepInput = z.infer<typeof workflowStepSchema>;
export type TriggerConfigInput = z.infer<typeof triggerConfigSchema>;
