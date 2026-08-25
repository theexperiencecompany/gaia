import {
  APPROVAL_REQUEST_TOOL_NAME,
  type ApprovalRequestData,
  type ApprovalStatus,
  SUBAGENT_GROUP_TOOL_NAME,
  type SubagentGroupData,
  TOOL_CALLS_DATA_TOOL_NAME,
  type ToolDataEntry,
} from "@gaia/shared/chat";
import { TOOL_RENDERERS } from "../../tool-data/renderers";
import type {
  ActivityStatus,
  ActivityToolCall,
  ApprovalLookup,
  EnrichedSubagentGroup,
  TimelineItem,
} from "./activity-format.types";

export type {
  ActivityStatus,
  ActivityToolCall,
  ApprovalLookup,
  EnrichedSubagentGroup,
  TimelineItem,
} from "./activity-format.types";

const PREVIEW_MAX_CHARS = 80;

/**
 * Human titles for the tools users actually see while they run
 * ("Checking email…"), matching decisions §2. Unmapped tools fall back to
 * their formatted name.
 */
const TOOL_TITLES: Record<string, string> = {
  web_search: "Searching the web",
  web_fetch: "Reading a page",
  email_search: "Checking email",
  email_fetch: "Checking email",
  read_email: "Reading email",
  send_email: "Sending email",
  reply_email: "Replying to email",
  calendar_list_events: "Checking calendar",
  calendar_create_event: "Creating event",
  calendar_delete_event: "Deleting event",
  calendar_edit_event: "Editing event",
  weather_search: "Checking weather",
  memory_create: "Storing memory",
  memory_search: "Searching memories",
  memory_list: "Retrieving memories",
  todo_create: "Adding todos",
  todo_list: "Checking todos",
  workflow_create: "Setting up workflow",
};

export function formatToolName(toolName: string): string {
  return toolName
    .toLowerCase()
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase())
    .replace(/\s+tool$/i, "")
    .trim();
}

export function humanToolTitle(toolName: string | null | undefined): string {
  if (!toolName) return "Thinking";
  const key = toolName.toLowerCase().replace(/[\s-]+/g, "_");
  return TOOL_TITLES[key] ?? formatToolName(toolName);
}

export function callStatus(call: ActivityToolCall): ActivityStatus {
  if (call.status) return call.status;
  return call.output ? "done" : "running";
}

function firstString(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = firstString(item);
      if (nested) return nested;
    }
    return null;
  }
  if (value && typeof value === "object") {
    for (const item of Object.values(value)) {
      const nested = firstString(item);
      if (nested) return nested;
    }
  }
  return null;
}

/** Text whose first non-whitespace char opens a JSON container — not a phrase. */
function isJsonishText(text: string): boolean {
  const trimmed = text.trimStart();
  return trimmed.startsWith("{") || trimmed.startsWith("[");
}

/** Truncate to ~PREVIEW_MAX_CHARS at a word boundary with an ellipsis. */
function truncateAtWord(text: string): string {
  const compact = text.replace(/\s+/g, " ").trim();
  if (compact.length <= PREVIEW_MAX_CHARS) return compact;
  const slice = compact.slice(0, PREVIEW_MAX_CHARS);
  const boundary = slice.lastIndexOf(" ");
  const clipped =
    boundary > PREVIEW_MAX_CHARS / 2 ? slice.slice(0, boundary) : slice;
  return `${clipped.trimEnd()}…`;
}

/** "5 results · 2 sources" phrases from array-valued entries. */
function countSummary(entries: [string, unknown][]): string | null {
  const parts: string[] = [];
  for (const [key, value] of entries) {
    if (parts.length >= 3) break;
    if (Array.isArray(value) && value.length > 0) {
      parts.push(`${value.length} ${key.toLowerCase()}`);
    }
  }
  return parts.length ? parts.join(" · ") : null;
}

function structuredPreview(value: unknown, depth = 0): string | null {
  if (Array.isArray(value)) {
    return value.length > 0 ? `${value.length} items` : null;
  }
  if (!isPlainObject(value)) return null;
  const direct = countSummary(Object.entries(value));
  if (direct) return direct;
  const values = Object.values(value);
  return depth === 0 && values.length === 1
    ? structuredPreview(values[0], depth + 1)
    : null;
}

/**
 * One-line ~80-char live preview for an activity row. Structured outputs
 * become short human phrases ("5 results · 2 sources"); raw JSON never
 * leaks into the line — if the best candidate is JSON-ish it is omitted.
 */
export function previewForCall(call: ActivityToolCall): string {
  if (call.message && !isJsonishText(call.message)) {
    return truncateAtWord(call.message);
  }

  const parsedOutput = call.output != null ? safeJsonParse(call.output) : null;
  if (parsedOutput !== null) {
    const summary = structuredPreview(parsedOutput);
    if (summary) return summary;
  }

  const inputCandidate = firstString(call.inputs);
  if (inputCandidate && !isJsonishText(inputCandidate)) {
    return truncateAtWord(inputCandidate);
  }

  if (
    typeof call.output === "string" &&
    call.output &&
    !isJsonishText(call.output)
  ) {
    return truncateAtWord(call.output);
  }
  return "";
}

// -- JSON formatting (moved verbatim from the deleted tool-calls-section) ----

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function safeJsonParse(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
}

interface NormalizedValue {
  data: unknown;
  isStructured: boolean;
}

function normalizeValue(value: unknown): NormalizedValue {
  if (value == null) return { data: "", isStructured: false };
  if (Array.isArray(value)) return { data: value, isStructured: true };
  if (isPlainObject(value)) return { data: value, isStructured: true };
  if (typeof value === "string") {
    const parsed = safeJsonParse(value);
    if (parsed !== null && (isPlainObject(parsed) || Array.isArray(parsed))) {
      return { data: parsed, isStructured: true };
    }
    return { data: value, isStructured: false };
  }
  return { data: String(value), isStructured: false };
}

/** Pretty text for an Input/Output panel — structured values pretty-printed. */
export function formatDetailText(content: unknown): string {
  const { data, isStructured } = normalizeValue(content);
  if (isStructured && typeof data !== "string") {
    return JSON.stringify(data, null, 2);
  }
  return String(data);
}

/**
 * If a tool call's output is exactly one typed payload that has a rich
 * renderer (`{"weather_data": {...}}`), returns [key, payload] so the caller
 * can render the full TOOL_RENDERERS card instead of raw text.
 */
export function matchRichRenderer(
  output: string | undefined,
): { key: string; data: unknown } | null {
  if (!output) return null;
  const parsed = safeJsonParse(output);
  if (!isPlainObject(parsed)) return null;
  const keys = Object.keys(parsed);
  if (keys.length !== 1) return null;
  const key = keys[0];
  if (!(key in TOOL_RENDERERS)) return null;
  return { key, data: parsed[key] };
}

// -- Unified tool-chain timeline ----------------------------------------------

const ORIGIN_TOOL_NAMES = new Set(["spawn_subagent", "handoff"]);

const isOriginCall = (call: ActivityToolCall): boolean =>
  call.tool_name != null && ORIGIN_TOOL_NAMES.has(call.tool_name.toLowerCase());

const taskFromInputs = (
  inputs?: Record<string, unknown>,
): string | undefined => {
  const task = inputs?.task;
  return typeof task === "string" && task ? task : undefined;
};

/** Merge adjacent reasoning fragments so one continuous thought is one row. */
function coalesceReasoning<T extends ActivityToolCall>(calls: T[]): T[] {
  const out: T[] = [];
  for (const call of calls) {
    const prev = out.at(-1);
    if (call.reasoning != null && prev?.reasoning != null) {
      out[out.length - 1] = {
        ...prev,
        reasoning: prev.reasoning + call.reasoning,
      };
      continue;
    }
    out.push(call);
  }
  return out;
}

/**
 * Attach the task/result carried by the group's own spawn/handoff call and
 * drop that call from the child rows — the group header IS the spawn row.
 */
function enrichGroup(group: EnrichedSubagentGroup): EnrichedSubagentGroup {
  const originCall = group.tool_calls.find(isOriginCall);
  return {
    ...group,
    tool_calls: coalesceReasoning(
      group.tool_calls.filter((tc) => !isOriginCall(tc)),
    ),
    nested_subagents: group.nested_subagents.map((nested) =>
      enrichGroup(nested as EnrichedSubagentGroup),
    ),
    handoff_input: group.handoff_input ?? taskFromInputs(originCall?.inputs),
    handoff_output: group.handoff_output ?? (originCall?.output || undefined),
  };
}

/**
 * Streamed `tool_calls_data` entries arrive one event per call (plus later
 * events carrying the output for an earlier call), so calls are merged
 * in-place keyed by tool_call_id.
 */
function mergePartialCalls(rawCalls: unknown[]): ActivityToolCall[] {
  const buffer: Record<string, unknown>[] = [];
  const idToIndex = new Map<string, number>();

  for (const rawCall of rawCalls) {
    const call = (rawCall ?? {}) as Record<string, unknown>;
    const id =
      typeof call.tool_call_id === "string" ? call.tool_call_id : undefined;

    if (id && idToIndex.has(id)) {
      const existingIndex = idToIndex.get(id) as number;
      buffer[existingIndex] = {
        ...(buffer[existingIndex] ?? {}),
        ...Object.fromEntries(
          Object.entries(call).filter(([, v]) => v !== undefined && v !== ""),
        ),
      };
      continue;
    }
    if (id) idToIndex.set(id, buffer.length);
    buffer.push(call);
  }

  return buffer as ActivityToolCall[];
}

/** Accumulating state while the timeline is built from toolData order. */
interface TimelineBuilder {
  items: TimelineItem[];
  /** A spawn/handoff call awaiting the subagent group it originated. */
  pendingOrigin: ActivityToolCall | null;
}

function flushPendingOrigin(builder: TimelineBuilder): void {
  if (!builder.pendingOrigin) return;
  builder.items.push({ kind: "tool", call: builder.pendingOrigin });
  builder.pendingOrigin = null;
}

function appendThinking(items: TimelineItem[], content: string): void {
  const prev = items.at(-1);
  if (prev?.kind === "thinking") {
    prev.content += content;
    return;
  }
  items.push({ kind: "thinking", content });
}

function appendCalls(
  builder: TimelineBuilder,
  calls: ActivityToolCall[],
): void {
  for (const call of calls) {
    if (call.reasoning != null) {
      flushPendingOrigin(builder);
      appendThinking(builder.items, call.reasoning);
      continue;
    }
    if (isOriginCall(call)) {
      // The spawn/handoff call IS the subagent row — hold its task/output
      // until the matching subagent_group entry arrives.
      flushPendingOrigin(builder);
      builder.pendingOrigin = call;
      continue;
    }
    flushPendingOrigin(builder);
    builder.items.push({ kind: "tool", call });
  }
}

function attachSubagentGroup(
  builder: TimelineBuilder,
  rawGroup: EnrichedSubagentGroup,
): void {
  const group = enrichGroup(rawGroup);
  if (builder.pendingOrigin) {
    const origin = builder.pendingOrigin;
    group.handoff_input = group.handoff_input ?? taskFromInputs(origin.inputs);
    group.handoff_output = group.handoff_output ?? (origin.output || undefined);
    builder.pendingOrigin = null;
  }
  builder.items.push({ kind: "subagent", group });
}

/** Every tool_call_id nested anywhere in a subagent group tree. */
function collectGroupedToolCallIds(toolData: ToolDataEntry[]): Set<string> {
  const ids = new Set<string>();
  const visit = (group: SubagentGroupData): void => {
    for (const tc of group.tool_calls) {
      if (tc.tool_call_id) ids.add(tc.tool_call_id);
    }
    for (const nested of group.nested_subagents) visit(nested);
  };
  for (const entry of toolData) {
    if (entry.tool_name === SUBAGENT_GROUP_TOOL_NAME) {
      visit(entry.data as SubagentGroupData);
    }
  }
  return ids;
}

/**
 * Build the unified chronological chain for one AI turn:
 * - `tool_calls_data` entries flatten into tool rows (partials merged by id),
 *   with entries carrying `reasoning` becoming coalesced thinking rows;
 * - `subagent_group` entries become subagent items at their entry order,
 *   with nested tool lists kept inside the group;
 * - root-level duplicates of calls already nested in a group are dropped;
 * - a root-level spawn/handoff call attaches its task/output to the following
 *   subagent group instead of rendering as its own row.
 */
export function buildTimeline(
  toolData: ToolDataEntry[] | undefined,
): TimelineItem[] {
  const builder: TimelineBuilder = { items: [], pendingOrigin: null };
  const groupedIds = collectGroupedToolCallIds(toolData ?? []);

  for (const entry of toolData ?? []) {
    if (entry.tool_name === SUBAGENT_GROUP_TOOL_NAME) {
      attachSubagentGroup(builder, entry.data as EnrichedSubagentGroup);
      continue;
    }
    if (entry.tool_name !== TOOL_CALLS_DATA_TOOL_NAME) continue;

    const data = entry.data;
    const calls = mergePartialCalls(Array.isArray(data) ? data : [data]).filter(
      (call) => !(call.tool_call_id && groupedIds.has(call.tool_call_id)),
    );
    appendCalls(builder, calls);
  }

  flushPendingOrigin(builder);
  return builder.items;
}

/** Scan toolData for HIL approval requests, split into pending and settled. */
export function buildApprovalLookup(
  toolData: ToolDataEntry[] | undefined,
): ApprovalLookup {
  const pendingToolCallIds = new Set<string>();
  const statusByToolCallId = new Map<string, ApprovalStatus>();

  for (const entry of toolData ?? []) {
    if (entry.tool_name !== APPROVAL_REQUEST_TOOL_NAME) continue;
    const data = entry.data as Partial<ApprovalRequestData> | null;
    if (!data?.tool_call_id || !data.status) continue;
    if (data.status === "pending") {
      pendingToolCallIds.add(data.tool_call_id);
    } else {
      statusByToolCallId.set(data.tool_call_id, data.status);
    }
  }

  return { pendingToolCallIds, statusByToolCallId };
}

/** Total real tool calls shown by a timeline (thinking rows excluded). */
export function countTimelineTools(items: TimelineItem[]): number {
  const countGroup = (group: SubagentGroupData): number => {
    let total = group.tool_calls.filter((tc) => tc.reasoning == null).length;
    for (const nested of group.nested_subagents) total += countGroup(nested);
    return total;
  };

  let count = 0;
  for (const item of items) {
    if (item.kind === "tool") count += 1;
    if (item.kind === "subagent") count += countGroup(item.group);
  }
  return count;
}
