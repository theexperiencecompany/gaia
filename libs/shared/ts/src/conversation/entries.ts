import { z } from "zod";
import type {
  ApprovalOutcome,
  ApprovalRequestEntry,
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
  ToolTimeline,
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

export const REPLY_OUTCOME = {
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
  tool_call_id: z.string().default(""),
  gated_tool_name: z.string().default(""),
  integration_name: z.string().nullable().default(null),
  args_preview: z.record(z.string(), z.unknown()).default({}),
  auto_reason: z.string().nullable().default(null),
  always_asks: z.boolean().default(false),
}) satisfies z.ZodType<ApprovalRequested>;

const APPROVAL_OUTCOMES = [
  "approved",
  "denied",
  "expired",
  "cancelled",
  "withdrawn",
] as const satisfies readonly ApprovalOutcome[];

const ApprovalCardSchema = z.object({
  tool_name: z.string(),
  tool_category: z.string(),
  timestamp: z.string(),
  data: z.object({
    approval_id: z.string(),
    tool_call_id: z.string(),
    gated_tool_name: z.string(),
    integration_name: z.string().nullable(),
    summary: z.string(),
    args_preview: z.record(z.string(), z.unknown()),
    outcome: z.enum(APPROVAL_OUTCOMES).nullable(),
    decider: z.enum(["user", "auto"]).nullable().optional(),
    action: z
      .enum(["executing", "executed", "failed", "unknown"])
      .nullable()
      .optional(),
    feedback: z.string().nullable(),
    auto_reason: z.string().nullable(),
    timeout_seconds: z.number().int(),
    asked_at: z.string().nullable().optional(),
    always_asks: z.boolean().optional(),
  }),
}) satisfies z.ZodType<ApprovalRequestEntry>;

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

/** Work whose cards are still streaming onto its item. */
export const LIVE_WORK_STATUS: ReadonlySet<string> = new Set([
  WORK_STATUS.RUNNING,
  WORK_STATUS.AWAITING_APPROVAL,
]);

const itemPlace = { id, seq: z.number().int().min(1), at: z.string() };

/** The tool thread and stand-alone cards the server folded an item's cards into. */
export const ToolTimelineSchema = z.object({
  steps: z.array(
    z.object({
      kind: z.enum(["tool", "subagent"]),
      key: z.string(),
      data: z.unknown(),
    }),
  ),
  cards: z.array(z.object({ key: z.string(), card: ToolDataEntrySchema })),
  progress: z
    .object({
      message: z.string().min(1),
      tool_name: z.string(),
      tool_category: z.string(),
      integration_name: z.string().nullable(),
      icon_url: z.string().nullable(),
      show_category: z.boolean(),
    })
    .nullable(),
}) satisfies z.ZodType<ToolTimeline>;

const UserItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.USER),
  ...itemPlace,
  message: UserMessageSchema,
}) satisfies z.ZodType<UserItem>;

const ReplyItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.REPLY),
  ...itemPlace,
  bubbles: z.array(z.string()),
  tool_data: z.array(ToolDataEntrySchema),
  timeline: ToolTimelineSchema,
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
  retry_target: z.string().nullable(),
  files: z.array(
    z.object({ path: z.string().min(1), content_type: z.string().nullable() }),
  ),
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
  asked_seq: z.number().int().min(0),
  approvals: z.array(ApprovalCardSchema),
  handoff: ToolDataEntrySchema.nullable(),
  tool_data: z.array(ToolDataEntrySchema),
  timeline: ToolTimelineSchema,
  image: ImageDataSchema.nullable(),
  retry_target: z.string().nullable(),
}) satisfies z.ZodType<WorkItem>;

const NoticeItemSchema = z.object({
  kind: z.literal(SCREEN_ITEM_KIND.NOTICE),
  ...itemPlace,
  bubbles: z.array(z.string()),
  tool_data: z.array(ToolDataEntrySchema),
  timeline: ToolTimelineSchema,
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
