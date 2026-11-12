import { z } from "zod";
import type {
  ApprovalDecided,
  ApprovalRequested,
  BargeIn,
  ConversationSource,
  IntegrationConnected,
  IntegrationNeeded,
  Notice,
  Reaction,
  Reply,
  ReplySettled,
  StopRequested,
  TodoRunWake,
  TodoWoke,
  UserMessage,
  WorkFinished,
  WorkflowFired,
  WorkStarted,
} from "../api/generated";
import { ToolDataEntrySchema } from "../chat/schema";

/** Zod mirror of the conversation log's entries, each tied to its generated API type. */

export const ENTRY_KIND = {
  USER_MESSAGE: "user_message",
  STOP_REQUESTED: "stop_requested",
  BARGE_IN: "barge_in",
  WORKFLOW_FIRED: "workflow_fired",
  TODO_WOKE: "todo_woke",
  NOTICE: "notice",
  WORK_STARTED: "work_started",
  APPROVAL_REQUESTED: "approval_requested",
  APPROVAL_DECIDED: "approval_decided",
  WORK_FINISHED: "work_finished",
  REPLY: "reply",
  REPLY_SETTLED: "reply_settled",
  INTEGRATION_NEEDED: "integration_needed",
  INTEGRATION_CONNECTED: "integration_connected",
} as const;

const REPLY_OUTCOME = {
  ANSWERED: "answered",
  STOPPED: "stopped",
  FAILED: "failed",
  SILENT: "silent",
} as const;

const MAY_ANSWER_NOTHING: ReadonlySet<string> = new Set([
  REPLY_OUTCOME.STOPPED,
  REPLY_OUTCOME.FAILED,
]);

const ConversationSourceSchema = z.enum([
  "web",
  "mobile",
  "desktop",
  "telegram",
  "discord",
  "slack",
  "whatsapp",
  "imessage",
  "workflow_system",
  "background",
]) satisfies z.ZodType<ConversationSource>;

const TodoRunWakeSchema = z.object({
  kind: z.enum(["schedule", "trigger", "approval"]),
  trigger_names: z.array(z.string()),
  approval_summary: z.string().nullable(),
}) satisfies z.ZodType<TodoRunWake>;

const id = z.string().min(1);
const revision = z.number().int().min(0).default(0);

export const ReactionSchema = z.object({
  emoji: z.string().min(1),
  by: z.enum(["jev", "chat_model"]),
}) satisfies z.ZodType<Reaction>;
const nullableString = z.string().nullable().default(null);

export const UserMessageSchema = z.object({
  kind: z.literal(ENTRY_KIND.USER_MESSAGE),
  id,
  text: z.string(),
  surface: ConversationSourceSchema,
  platform_message_id: nullableString,
  reply_to: nullableString,
  retry_of: nullableString,
  file_ids: z.array(z.string()).default([]),
  voice: z.boolean().default(false),
  reaction: ReactionSchema.nullable().default(null),
  revision,
}) satisfies z.ZodType<UserMessage>;

const StopRequestedSchema = z.object({
  kind: z.literal(ENTRY_KIND.STOP_REQUESTED),
  id,
  by: z.enum(["user", "gaia"]),
  covers_through: z.number().int().min(0).nullable().default(null),
}) satisfies z.ZodType<StopRequested>;

const BargeInSchema = z.object({
  kind: z.literal(ENTRY_KIND.BARGE_IN),
  id,
  reply_id: z.string(),
  heard_text: z.string(),
}) satisfies z.ZodType<BargeIn>;

const WorkflowFiredSchema = z.object({
  kind: z.literal(ENTRY_KIND.WORKFLOW_FIRED),
  id,
  workflow_id: z.string(),
  execution_id: z.string(),
  context: z.record(z.string(), z.unknown()),
}) satisfies z.ZodType<WorkflowFired>;

const TodoWokeSchema = z.object({
  kind: z.literal(ENTRY_KIND.TODO_WOKE),
  id,
  todo_id: z.string(),
  wake: TodoRunWakeSchema,
}) satisfies z.ZodType<TodoWoke>;

const NoticeSchema = z.object({
  kind: z.literal(ENTRY_KIND.NOTICE),
  id,
  text: z.string(),
  origin: z.string(),
}) satisfies z.ZodType<Notice>;

const WorkStartedSchema = z.object({
  kind: z.literal(ENTRY_KIND.WORK_STARTED),
  id,
  task_id: z.string(),
  cause_through: z.number().int().min(1),
  answers: z.array(z.string()).default([]),
}) satisfies z.ZodType<WorkStarted>;

const ApprovalRequestedSchema = z.object({
  kind: z.literal(ENTRY_KIND.APPROVAL_REQUESTED),
  id,
  task_id: z.string(),
  approval_id: z.string(),
}) satisfies z.ZodType<ApprovalRequested>;

const ApprovalDecidedSchema = z.object({
  kind: z.literal(ENTRY_KIND.APPROVAL_DECIDED),
  id,
  approval_id: z.string(),
  decision: z.enum(["approve", "deny", "timeout", "abandon"]),
}) satisfies z.ZodType<ApprovalDecided>;

const WorkFinishedSchema = z.object({
  kind: z.literal(ENTRY_KIND.WORK_FINISHED),
  id,
  task_id: z.string(),
  outcome: z.enum(["done", "failed", "cancelled", "lost"]),
  report: z.string(),
}) satisfies z.ZodType<WorkFinished>;

export const ReplySchema = z.object({
  kind: z.literal(ENTRY_KIND.REPLY),
  id,
  reply_id: z.string(),
  attempt_id: z.string(),
  text: z.string().default(""),
  tool_data: z.array(ToolDataEntrySchema).default([]),
  follow_up_actions: z.array(z.string()).default([]),
  heard_through: z.number().int().min(0).nullable().default(null),
  revision,
}) satisfies z.ZodType<Reply>;

const ReplySettledSchema = z
  .object({
    kind: z.literal(ENTRY_KIND.REPLY_SETTLED),
    id,
    reply_id: z.string(),
    outcome: z.enum([
      REPLY_OUTCOME.ANSWERED,
      REPLY_OUTCOME.STOPPED,
      REPLY_OUTCOME.FAILED,
      REPLY_OUTCOME.SILENT,
    ]),
    answers: z.array(z.string()),
    through: z.number().int().min(1),
    quote_target: z.string().nullable(),
  })
  .refine(
    (entry) =>
      entry.answers.length > 0 || MAY_ANSWER_NOTHING.has(entry.outcome),
    { message: "an answered or silent reply answers at least one entry" },
  ) satisfies z.ZodType<ReplySettled>;

const IntegrationNeededSchema = z.object({
  kind: z.literal(ENTRY_KIND.INTEGRATION_NEEDED),
  id,
  integration_id: z.string(),
  integration_name: z.string(),
}) satisfies z.ZodType<IntegrationNeeded>;

const IntegrationConnectedSchema = z.object({
  kind: z.literal(ENTRY_KIND.INTEGRATION_CONNECTED),
  id,
  integration_id: z.string(),
  integration_name: z.string(),
  needed_id: z.string(),
}) satisfies z.ZodType<IntegrationConnected>;

export const EntrySchema = z.discriminatedUnion("kind", [
  UserMessageSchema,
  StopRequestedSchema,
  BargeInSchema,
  WorkflowFiredSchema,
  TodoWokeSchema,
  NoticeSchema,
  WorkStartedSchema,
  ApprovalRequestedSchema,
  ApprovalDecidedSchema,
  WorkFinishedSchema,
  ReplySchema,
  ReplySettledSchema,
  IntegrationNeededSchema,
  IntegrationConnectedSchema,
]);
