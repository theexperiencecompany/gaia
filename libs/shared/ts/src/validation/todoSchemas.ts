import { z } from "zod";

const PRIORITY_VALUES = ["high", "medium", "low", "none"] as const;

export const createTodoSchema = z.object({
  title: z
    .string()
    .min(1, "Title is required")
    .max(500, "Title must be 500 characters or fewer"),
  description: z.string().max(5000).optional(),
  dueDate: z.string().datetime({ offset: true }).optional(),
  priority: z.enum(PRIORITY_VALUES).optional().default("none"),
  labels: z.array(z.string().min(1).max(100)).max(20).optional().default([]),
  projectId: z.string().optional(),
});

export const updateTodoSchema = z.object({
  title: z
    .string()
    .min(1, "Title is required")
    .max(500, "Title must be 500 characters or fewer")
    .optional(),
  description: z.string().max(5000).optional(),
  dueDate: z.string().datetime({ offset: true }).optional(),
  priority: z.enum(PRIORITY_VALUES).optional(),
  labels: z.array(z.string().min(1).max(100)).max(20).optional(),
  projectId: z.string().optional(),
  completed: z.boolean().optional(),
});

export type CreateTodoInput = z.infer<typeof createTodoSchema>;
export type UpdateTodoInput = z.infer<typeof updateTodoSchema>;
