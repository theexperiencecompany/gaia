// apps/web/src/features/recording/types/scenario.ts
import { z } from "zod";

// ── Zod schemas ──────────────────────────────────────────────────────────────

export const ToolInfoSchema = z.object({
  toolCategory: z.string().optional(),
  integrationName: z.string().optional(),
  iconUrl: z.string().optional(),
  showCategory: z.boolean().optional(),
});

const BaseStateSchema = z.object({
  pauseAfter: z.number().optional().default(300),
  duration: z.number().optional(),
});

export const UserMessageStateSchema = BaseStateSchema.extend({
  type: z.literal("user_message"),
  text: z.string().min(1),
  typingSpeed: z.number().optional().default(50),
});

export const BotMessageStateSchema = BaseStateSchema.extend({
  type: z.literal("bot_message"),
  text: z.string(),
  streamingSpeed: z.number().optional().default(15),
  tool_data: z.array(z.any()).optional(),
  follow_up_actions: z.array(z.string()).optional(),
  image_data: z.any().optional(),
  memory_data: z.any().optional(),
});

export const LoadingStateSchema = BaseStateSchema.extend({
  type: z.literal("loading"),
  text: z.string(),
  toolInfo: ToolInfoSchema.optional(),
  duration: z.number().default(1500),
});

export const ToolCallsStateSchema = BaseStateSchema.extend({
  type: z.literal("tool_calls"),
  entries: z.array(z.any()).min(1),
});

export const ThinkingStateSchema = BaseStateSchema.extend({
  type: z.literal("thinking"),
  content: z.string().min(1),
  duration: z.number().optional().default(2000),
});

export const TodoDataStateSchema = BaseStateSchema.extend({
  type: z.literal("todo_data"),
  data: z.any(),
});

export const ImageStateSchema = BaseStateSchema.extend({
  type: z.literal("image"),
  image_data: z.object({
    url: z.string(),
    prompt: z.string().optional(),
    improved_prompt: z.string().nullable().optional(),
  }),
});

export const PauseStateSchema = BaseStateSchema.extend({
  type: z.literal("pause"),
  duration: z.number().min(100),
});

export const ScenarioStateSchema = z.discriminatedUnion("type", [
  UserMessageStateSchema,
  BotMessageStateSchema,
  LoadingStateSchema,
  ToolCallsStateSchema,
  ThinkingStateSchema,
  TodoDataStateSchema,
  ImageStateSchema,
  PauseStateSchema,
]);

export const ScenarioSettingsSchema = z.object({
  theme: z.enum(["dark", "light"]).optional().default("dark"),
});

export const ScenarioSchema = z.object({
  id: z.string().min(1),
  title: z.string().min(1),
  viewport: z
    .object({
      width: z.number().positive(),
      height: z.number().positive(),
    })
    .optional()
    .default({ width: 390, height: 844 }),
  settings: ScenarioSettingsSchema.optional().default({}),
  states: z.array(ScenarioStateSchema).min(1),
});

// ── TypeScript types (derived from Zod) ──────────────────────────────────────

export type ToolInfo = z.infer<typeof ToolInfoSchema>;
export type UserMessageState = z.infer<typeof UserMessageStateSchema>;
export type BotMessageState = z.infer<typeof BotMessageStateSchema>;
export type LoadingState = z.infer<typeof LoadingStateSchema>;
export type ToolCallsState = z.infer<typeof ToolCallsStateSchema>;
export type ThinkingState = z.infer<typeof ThinkingStateSchema>;
export type TodoDataState = z.infer<typeof TodoDataStateSchema>;
export type ImageState = z.infer<typeof ImageStateSchema>;
export type PauseState = z.infer<typeof PauseStateSchema>;
export type ScenarioState = z.infer<typeof ScenarioStateSchema>;
export type Scenario = z.infer<typeof ScenarioSchema>;

export type ScenarioPlayerPhase = "idle" | "playing" | "done" | "error";
