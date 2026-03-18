import { z } from "zod";

/**
 * Loose cron expression pattern: 5 or 6 space-separated fields.
 * Full cron syntax validation is left to the backend.
 */
const cronStringSchema = z
  .string()
  .min(1, "Schedule (cron expression) is required")
  .regex(
    /^(\S+\s+){4}\S+(\s+\S+)?$/,
    "Must be a valid cron expression (e.g. '0 9 * * *')",
  );

export const createReminderSchema = z.object({
  title: z
    .string()
    .min(1, "Title is required")
    .max(200, "Title must be 200 characters or fewer"),
  schedule: cronStringSchema,
  message: z
    .string()
    .max(1000, "Message must be 1000 characters or fewer")
    .optional(),
  timezone: z.string().optional(),
});

export const updateReminderSchema = z.object({
  title: z.string().min(1).max(200).optional(),
  schedule: cronStringSchema.optional(),
  message: z.string().max(1000).optional(),
  timezone: z.string().optional(),
  status: z.enum(["active", "paused"]).optional(),
});

export type CreateReminderInput = z.infer<typeof createReminderSchema>;
export type UpdateReminderInput = z.infer<typeof updateReminderSchema>;
