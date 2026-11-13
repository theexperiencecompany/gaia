import { z } from "zod";
import type {
  ApprovalRequested,
  ConversationSource,
  FailureReason,
  FileData,
  ImageData,
  NoticeItem,
  Reaction,
  ReplyItem,
  ReplyToMessageData,
  SelectedCalendarEventData,
  SelectedWorkflowDataOutput,
  TodoRunWake,
  TodoWokeItem,
  UserItem,
  UserMessage,
  WorkflowFiredItem,
  WorkItem,
} from "../api/generated";
import { ToolDataEntrySchema } from "../chat/schema";

/** Zod mirror of the screen's items and the log entries they carry, each tied to its generated API type. */

// The entry kinds a screen item carries whole.
const ENTRY_KIND = {
  USER_MESSAGE: "user_message",
  APPROVAL_REQUESTED: "approval_requested",
} as const;

const REPLY_OUTCOME = {
  ANSWERED: "answered",
  STOPPED: "stopped",
  TRUNCATED: "truncated",
  FAILED: "failed",
  SILENT: "silent",
} as const;

export const FAILURE_REASON = {
  MODEL_ERROR: "model_error",
  STEP_LIMIT: "step_limit",
  SERVER_RESTART: "server_restart",
} as const satisfies Record<string, FailureReason>;

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

const ReactionSchema = z.object({
  emoji: z.string().min(1),
  by: z.enum(["jev", "chat_model"]),
}) satisfies z.ZodType<Reaction>;
const nullableString = z.string().nullable().default(null);
const optionalString = z.string().nullish();

const FileDataSchema = z.object({
  fileId: z.string(),
  filename: z.string(),
  url: z.string(),
  description: optionalString,
  message: optionalString,
  sandbox_path: optionalString,
  type: optionalString,
}) satisfies z.ZodType<FileData>;

const ImageDataSchema = z.object({
  url: z.string(),
  prompt: z.string(),
  improved_prompt: optionalString,
}) satisfies z.ZodType<ImageData>;

const SelectedWorkflowSchema = z.object({
  id: z.string(),
  title: z.string(),
  description: z.string(),
  prompt: optionalString,
  steps: z.array(
    z.object({
      id: z.string(),
      title: z.string(),
      description: z.string(),
      category: z.string(),
    }),
  ),
}) satisfies z.ZodType<SelectedWorkflowDataOutput>;

const CalendarEventTimeSchema = z
  .object({
    date: optionalString,
    dateTime: optionalString,
    timeZone: optionalString,
  })
  .loose();

const SelectedCalendarEventSchema = z.object({
  id: z.string(),
  summary: z.string(),
  description: z.string(),
  start: CalendarEventTimeSchema,
  end: CalendarEventTimeSchema,
  backgroundColor: optionalString,
  calendarId: optionalString,
  calendarTitle: optionalString,
  isAllDay: z.boolean().nullish(),
}) satisfies z.ZodType<SelectedCalendarEventData>;

const ReplyToMessageSchema = z.object({
  id: z.string(),
  content: z.string(),
  role: z.enum(["user", "assistant"]),
}) satisfies z.ZodType<ReplyToMessageData>;

const UserMessageSchema = z.object({
  kind: z.literal(ENTRY_KIND.USER_MESSAGE),
  id,
  text: z.string(),
  surface: ConversationSourceSchema,
  platform_message_id: nullableString,
  reply_to: nullableString,
  retry_of: nullableString,
  file_ids: z.array(z.string()).default([]),
  files: z.array(FileDataSchema).default([]),
  selected_tool: nullableString,
  tool_category: nullableString,
  selected_workflow: SelectedWorkflowSchema.nullable().default(null),
  selected_calendar_event: SelectedCalendarEventSchema.nullable().default(null),
  reply_to_message: ReplyToMessageSchema.nullable().default(null),
  voice: z.boolean().default(false),
  reaction: ReactionSchema.nullable().default(null),
  todo_run_wake: TodoRunWakeSchema.nullable().default(null),
  posthog_session_id: nullableString,
  first_contact: z.boolean().default(false),
  pinned: z.boolean().default(false),
  imported: z.boolean().default(false),
  revision,
}) satisfies z.ZodType<UserMessage>;

const ApprovalRequestedSchema = z.object({
  kind: z.literal(ENTRY_KIND.APPROVAL_REQUESTED),
  id,
  task_id: z.string(),
  approval_id: z.string(),
  summary: z.string().default(""),
  expires_at: z.iso.datetime({ offset: true }).nullable().default(null),
}) satisfies z.ZodType<ApprovalRequested>;

export const SCREEN_ITEM_KIND = {
  USER: "user",
  REPLY: "reply",
  WORK: "work",
  NOTICE: "notice",
  WORKFLOW_FIRED: "workflow_fired",
  TODO_WOKE: "todo_woke",
} as const;

export const WORK_STATUS = {
  RUNNING: "running",
  AWAITING_APPROVAL: "awaiting_approval",
  DONE: "done",
  FAILED: "failed",
  CANCELLED: "cancelled",
  LOST: "lost",
} as const satisfies Record<string, WorkItem["status"]>;

const itemPlace = { id, seq: z.number().int().min(1), at: z.string() };

const UserItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.USER),
  ...itemPlace,
  message: UserMessageSchema,
}) satisfies z.ZodType<UserItem>;

const ReplyItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.REPLY),
  ...itemPlace,
  text: z.string(),
  tool_data: z.array(ToolDataEntrySchema),
  follow_up_actions: z.array(z.string()),
  image: ImageDataSchema.nullable(),
  pinned: z.boolean(),
  quote: ReplyToMessageSchema.nullable(),
  outcome: z
    .enum([
      REPLY_OUTCOME.ANSWERED,
      REPLY_OUTCOME.STOPPED,
      REPLY_OUTCOME.TRUNCATED,
      REPLY_OUTCOME.FAILED,
      REPLY_OUTCOME.SILENT,
    ])
    .nullable(),
  failure: z
    .enum([
      FAILURE_REASON.MODEL_ERROR,
      FAILURE_REASON.STEP_LIMIT,
      FAILURE_REASON.SERVER_RESTART,
    ])
    .nullable(),
  narrates: z.array(z.string()),
}) satisfies z.ZodType<ReplyItem>;

const WorkItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.WORK),
  ...itemPlace,
  task_id: z.string(),
  status: z.enum([
    WORK_STATUS.RUNNING,
    WORK_STATUS.AWAITING_APPROVAL,
    WORK_STATUS.DONE,
    WORK_STATUS.FAILED,
    WORK_STATUS.CANCELLED,
    WORK_STATUS.LOST,
  ]),
  asking: z.array(ApprovalRequestedSchema),
  handoff: ToolDataEntrySchema.nullable(),
  tool_data: z.array(ToolDataEntrySchema),
  image: ImageDataSchema.nullable(),
}) satisfies z.ZodType<WorkItem>;

const NoticeItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.NOTICE),
  ...itemPlace,
  text: z.string(),
  tool_data: z.array(ToolDataEntrySchema),
  follow_up_actions: z.array(z.string()),
}) satisfies z.ZodType<NoticeItem>;

const WorkflowFiredItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.WORKFLOW_FIRED),
  ...itemPlace,
  workflow: SelectedWorkflowSchema,
}) satisfies z.ZodType<WorkflowFiredItem>;

const TodoWokeItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.TODO_WOKE),
  ...itemPlace,
  wake: TodoRunWakeSchema,
}) satisfies z.ZodType<TodoWokeItem>;

/** One item of the screen the server projects from the log. */
export const ScreenItemSchema = z.discriminatedUnion("kind", [
  UserItemSchema,
  ReplyItemSchema,
  WorkItemSchema,
  NoticeItemSchema,
  WorkflowFiredItemSchema,
  TodoWokeItemSchema,
]);
