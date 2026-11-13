import { z } from "zod";
import type {
  ApprovalDecided,
  ApprovalRequested,
  Attribution,
  BargeIn,
  ConversationSource,
  FailureReason,
  FileData,
  ImageData,
  IntegrationConnected,
  IntegrationNeeded,
  Notice,
  Reaction,
  Reply,
  ReplySettled,
  ReplyToMessageData,
  SelectedCalendarEventData,
  SelectedWorkflowDataOutput,
  StopRequested,
  TodoRun,
  TodoRunWake,
  TodoWoke,
  UserMessage,
  WorkFinished,
  WorkflowFired,
  WorkflowRun,
  WorkflowTriggerContext,
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
  TRUNCATED: "truncated",
  FAILED: "failed",
  SILENT: "silent",
} as const;

export const FAILURE_REASON = {
  MODEL_ERROR: "model_error",
  STEP_LIMIT: "step_limit",
  SERVER_RESTART: "server_restart",
} as const satisfies Record<string, FailureReason>;

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

export const UserMessageSchema = z.object({
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
  heard_through: z.number().int().min(0),
}) satisfies z.ZodType<BargeIn>;

const AttributionSchema = z.object({
  actor: z.enum(["user", "agent"]),
  surface: z.enum(["web", "desktop", "bot", "voice", "worker"]),
  trigger: z.enum([
    "interactive",
    "schedule",
    "integration_trigger",
    "webhook",
    "system",
  ]),
}) satisfies z.ZodType<Attribution>;

const WorkflowTriggerSchema = z
  .object({
    type: optionalString,
    workflow_id: optionalString,
    triggered_at: z.string().optional(),
    trigger_data: z.record(z.string(), z.unknown()).optional(),
    email_data: z
      .object({
        message_text: z.string().optional(),
        sender: z.string().optional(),
        subject: z.string().optional(),
      })
      .optional(),
    playbook_fallback: optionalString,
    quiet_hours: z
      .discriminatedUnion("kind", [
        z.object({ kind: z.literal("bypass"), reason: z.string() }),
        z.object({ kind: z.literal("hold") }),
      ])
      .nullish(),
    tracked_todos_context: z.string().optional(),
    workflow_notify_on_completion: z.boolean().optional(),
  })
  .loose() satisfies z.ZodType<WorkflowTriggerContext>;

const WorkflowRunSchema = z.object({
  workflow: SelectedWorkflowSchema,
  execution_id: z.string(),
  timezone: z.string(),
  trigger: WorkflowTriggerSchema,
  attribution: AttributionSchema,
}) satisfies z.ZodType<WorkflowRun>;

const WorkflowFiredSchema = z.object({
  kind: z.literal(ENTRY_KIND.WORKFLOW_FIRED),
  id,
  run: WorkflowRunSchema,
}) satisfies z.ZodType<WorkflowFired>;

const TodoRunSchema = z.object({
  todo_id: z.string(),
  run_id: z.string(),
  title: z.string(),
  trigger_type: z.enum([
    "manual",
    "schedule",
    "integration",
    "scheduled_todo",
    "todo_trigger",
  ]),
  runs_once: z.boolean(),
  wake: TodoRunWakeSchema,
  report_form: z.enum(["write_up", "as_written"]),
  attribution: AttributionSchema,
}) satisfies z.ZodType<TodoRun>;

const TodoWokeSchema = z.object({
  kind: z.literal(ENTRY_KIND.TODO_WOKE),
  id,
  run: TodoRunSchema,
}) satisfies z.ZodType<TodoWoke>;

const NoticeSchema = z.object({
  kind: z.literal(ENTRY_KIND.NOTICE),
  id,
  text: z.string(),
  origin: z.string(),
  tool_data: z.array(ToolDataEntrySchema).default([]),
  follow_up_actions: z.array(z.string()).default([]),
}) satisfies z.ZodType<Notice>;

const WorkStartedSchema = z.object({
  kind: z.literal(ENTRY_KIND.WORK_STARTED),
  id,
  task_id: z.string(),
  cause_through: z.number().int().min(1),
  answers: z.array(z.string()).default([]),
  joins: nullableString,
  detached: z.boolean().default(false),
  exclusive: z.boolean().default(false),
}) satisfies z.ZodType<WorkStarted>;

const ApprovalRequestedSchema = z.object({
  kind: z.literal(ENTRY_KIND.APPROVAL_REQUESTED),
  id,
  task_id: z.string(),
  approval_id: z.string(),
  summary: z.string().default(""),
  expires_at: z.iso.datetime({ offset: true }).nullable().default(null),
}) satisfies z.ZodType<ApprovalRequested>;

const ApprovalDecidedSchema = z.object({
  kind: z.literal(ENTRY_KIND.APPROVAL_DECIDED),
  id,
  approval_id: z.string(),
  outcome: z.enum(["approved", "denied", "expired", "cancelled", "withdrawn"]),
  decider: z.enum(["user", "auto"]).nullable().default(null),
  action: z
    .enum(["executing", "executed", "failed", "unknown"])
    .nullable()
    .default(null),
}) satisfies z.ZodType<ApprovalDecided>;

const WorkFinishedSchema = z.object({
  kind: z.literal(ENTRY_KIND.WORK_FINISHED),
  id,
  task_id: z.string(),
  outcome: z.enum(["done", "failed", "cancelled", "lost"]),
  report: z.string(),
  tool_data: z.array(ToolDataEntrySchema).default([]),
  note: z.string().default(""),
  nothing_for_user: z.boolean().default(false),
  image: ImageDataSchema.nullable().default(null),
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
  quote_target: nullableString,
  image: ImageDataSchema.nullable().default(null),
  pinned: z.boolean().default(false),
  imported: z.boolean().default(false),
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
      REPLY_OUTCOME.TRUNCATED,
      REPLY_OUTCOME.FAILED,
      REPLY_OUTCOME.SILENT,
    ]),
    answers: z.array(z.string()),
    through: z.number().int().min(0),
    quote_target: z.string().nullable(),
    failure: z
      .enum([
        FAILURE_REASON.MODEL_ERROR,
        FAILURE_REASON.STEP_LIMIT,
        FAILURE_REASON.SERVER_RESTART,
      ])
      .nullable()
      .default(null),
    imported: z.boolean().default(false),
  })
  .refine(
    (entry) =>
      (entry.failure === null) !== (entry.outcome === REPLY_OUTCOME.FAILED),
    { message: "a failed reply names its failure, and only a failed one does" },
  )
  .refine(
    (entry) =>
      entry.answers.length > 0 ||
      MAY_ANSWER_NOTHING.has(entry.outcome) ||
      entry.imported,
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
