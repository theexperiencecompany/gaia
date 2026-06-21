import { TOOL_CALLS_DATA_TOOL_NAME } from "@shared/chat";
import React from "react";

import {
  GROUPED_TOOLS,
  type SubagentGroupData,
  type ToolCallEntry,
  type ToolDataEntry,
  type ToolDataMap,
  type ToolName,
} from "@/config/registries/toolRegistry";
import type { EnrichedSubagentGroup, TimelineItem } from "../UnifiedToolThread";

// ── Bucketing ────────────────────────────────────────────────────────────────

interface BucketedToolData {
  groupedEntries: ToolDataEntry[];
  individual: ToolDataEntry[];
  toolCalls: ToolCallEntry[];
  subagentGroups: SubagentGroupData[];
}

// Single pass over tool_data: route each entry into the right bucket and
// collapse tools listed in GROUPED_TOOLS into one entry per tool name.
function bucketToolData(
  tool_data: ToolDataEntry[] | null | undefined,
): BucketedToolData {
  const grouped = new Map<ToolName, ToolDataMap[ToolName][]>();
  const individual: ToolDataEntry[] = [];
  const toolCalls: ToolCallEntry[] = [];
  const subagentGroups: SubagentGroupData[] = [];

  tool_data?.forEach((entry) => {
    const toolName = entry.tool_name;

    if (toolName === TOOL_CALLS_DATA_TOOL_NAME) {
      // tool_calls_data is rendered via UnifiedToolThread, not via TOOL_RENDERERS.
      const calls = Array.isArray(entry.data)
        ? (entry.data as ToolCallEntry[])
        : [entry.data as ToolCallEntry];
      toolCalls.push(...calls);
      return;
    }

    if (toolName === "subagent_group") {
      subagentGroups.push(entry.data as SubagentGroupData);
      return;
    }

    if (GROUPED_TOOLS.has(toolName)) {
      const bucket = grouped.get(toolName) ?? [];
      bucket.push(entry.data);
      grouped.set(toolName, bucket);
      return;
    }

    individual.push(entry);
  });

  const groupedEntries: ToolDataEntry[] = Array.from(grouped.entries()).map(
    ([toolName, dataArray]) => ({
      tool_name: toolName,
      tool_category: "",
      data: dataArray as ToolDataMap[ToolName],
      timestamp: null,
    }),
  );

  return { groupedEntries, individual, toolCalls, subagentGroups };
}

// ── Shared helpers ───────────────────────────────────────────────────────────

// Merge consecutive reasoning steps into one. A single continuous thought can
// arrive as several adjacent reasoning entries (e.g. when an interleaved tool
// call between them was nested into a subagent group and dropped from this
// level), which would otherwise render as several separate "Thinking" rows for
// one block. Only truly adjacent reasoning is merged — a real tool call between
// two thoughts still separates them, preserving chronological order.
function coalesceReasoning(calls: ToolCallEntry[]): ToolCallEntry[] {
  const out: ToolCallEntry[] = [];
  for (const tc of calls) {
    const prev = out.at(-1);
    if (tc.reasoning != null && prev?.reasoning != null) {
      out[out.length - 1] = {
        ...prev,
        reasoning: prev.reasoning + tc.reasoning,
      };
      continue;
    }
    out.push(tc);
  }
  return out;
}

// Same coalescing for the root-level timeline, where reasoning steps are
// `kind: "tool"` items carrying a `reasoning` field.
function coalesceTimelineReasoning(timeline: TimelineItem[]): TimelineItem[] {
  const out: TimelineItem[] = [];
  for (const item of timeline) {
    const prev = out.at(-1);
    if (
      item.kind === "tool" &&
      item.data.reasoning != null &&
      prev?.kind === "tool" &&
      prev.data.reasoning != null
    ) {
      out[out.length - 1] = {
        kind: "tool",
        data: {
          ...prev.data,
          reasoning: prev.data.reasoning + item.data.reasoning,
        },
      };
      continue;
    }
    out.push(item);
  }
  return out;
}

function extractTaskFromInputs(
  inputs: ToolCallEntry["inputs"],
): string | undefined {
  if (!inputs || typeof inputs !== "object") return undefined;
  const task = inputs.task;
  return typeof task === "string" && task ? task : undefined;
}

function isHandoffCall(tc: ToolCallEntry, lowerMsg: string): boolean {
  return tc.tool_name === "handoff" || lowerMsg.startsWith("handing off to");
}

function isSpawnCall(tc: ToolCallEntry, lowerMsg: string): boolean {
  return tc.tool_name === "spawn_subagent" || lowerMsg === "spawning subagent";
}

// ── Backend-provided groups: deduplicate + enrich ────────────────────────────

function collectAllSubagentToolCallIds(
  groups: SubagentGroupData[],
): Set<string> {
  const ids = new Set<string>();
  const visit = (gs: SubagentGroupData[]): void => {
    for (const g of gs) {
      for (const tc of g.tool_calls) {
        if (tc.tool_call_id) ids.add(tc.tool_call_id);
      }
      visit(g.nested_subagents);
    }
  };
  visit(groups);
  return ids;
}

function deepEnrichGroup(g: SubagentGroupData): EnrichedSubagentGroup {
  return {
    ...g,
    tool_calls: coalesceReasoning(g.tool_calls),
    nested_subagents: g.nested_subagents.map(deepEnrichGroup),
  };
}

function flattenEnrichedGroups(
  groups: EnrichedSubagentGroup[],
): EnrichedSubagentGroup[] {
  const all: EnrichedSubagentGroup[] = [];
  const visit = (gs: EnrichedSubagentGroup[]): void => {
    for (const g of gs) {
      all.push(g);
      visit(g.nested_subagents);
    }
  };
  visit(groups);
  return all;
}

function matchHandoffGroupByName(
  groups: EnrichedSubagentGroup[],
  lowerMsg: string,
): EnrichedSubagentGroup | undefined {
  return groups.find(
    (g) =>
      g.agent_type === "handoff" &&
      lowerMsg.includes(g.subagent_name.toLowerCase()),
  );
}

function attachHandoffPayload(
  group: EnrichedSubagentGroup,
  task: string | undefined,
  output: string | undefined,
): void {
  if (task) group.handoff_input = task;
  if (output) group.handoff_output = output;
}

// Frontend nesting inference: if a handoff group contains a spawn_subagent
// call, nest the next unmatched root-level spawned group inside it. Handles
// data persisted before parent_subagent_id was propagated correctly.
function inferNestingForRootSpawned(
  finalGroups: EnrichedSubagentGroup[],
): EnrichedSubagentGroup[] {
  const rootSpawned = finalGroups.filter((g) => g.agent_type === "spawned");
  if (rootSpawned.length === 0) return finalGroups;

  let spawnIdx = 0;
  for (const g of finalGroups) {
    if (g.agent_type !== "handoff") continue;
    const hasSpawnCall = g.tool_calls.some(
      (tc) => tc.tool_name === "spawn_subagent",
    );
    if (!hasSpawnCall || spawnIdx >= rootSpawned.length) continue;
    g.nested_subagents.push(rootSpawned[spawnIdx++]);
  }

  const nestedIds = new Set(
    finalGroups
      .filter((g) => g.agent_type === "handoff")
      .flatMap((g) => g.nested_subagents.map((n) => n.subagent_id)),
  );
  return finalGroups.filter((g) => !nestedIds.has(g.subagent_id));
}

// Emit a backend subagent group at its originating tool call's position
// (handoff or spawn). Attaches the call's task/output to the group and
// records the group id so the trailing "append-unmatched" pass doesn't
// re-emit it. Returns the matched group, or null if no match was found.
function emitGroupForCall(
  tc: ToolCallEntry,
  isHandoff: boolean,
  allGroups: EnrichedSubagentGroup[],
  unmatchedSpawned: EnrichedSubagentGroup[],
  spawnIdxRef: { value: number },
  timeline: TimelineItem[],
  emittedGroupIds: Set<string>,
): void {
  let matched: EnrichedSubagentGroup | undefined;
  if (isHandoff) {
    matched = matchHandoffGroupByName(
      allGroups,
      (tc.message || "").toLowerCase(),
    );
  } else if (spawnIdxRef.value < unmatchedSpawned.length) {
    matched = unmatchedSpawned[spawnIdxRef.value++];
  }
  if (!matched) return;

  attachHandoffPayload(
    matched,
    extractTaskFromInputs(tc.inputs),
    tc.output || undefined,
  );
  if (emittedGroupIds.has(matched.subagent_id)) return;
  timeline.push({ kind: "subagent", data: matched });
  emittedGroupIds.add(matched.subagent_id);
}

// Walk the executor's tool-call stream once, interleaving backend-provided
// subagent groups at the position of their originating handoff/spawn call so
// the rendered timeline matches emission order. Each handoff/spawn tool call
// is consumed (attaching its inputs.task and outputs to the matched group);
// every other tool call passes through as a root-level timeline item.
function buildBackendTimeline(
  toolCalls: ToolCallEntry[],
  subagentGroups: SubagentGroupData[],
): TimelineItem[] {
  const subagentToolCallIds = collectAllSubagentToolCallIds(subagentGroups);
  const finalGroups = inferNestingForRootSpawned(
    subagentGroups.map(deepEnrichGroup),
  );
  const allGroups = flattenEnrichedGroups(finalGroups);
  const unmatchedSpawned = allGroups.filter((g) => g.agent_type === "spawned");
  const spawnIdxRef = { value: 0 };
  const emittedGroupIds = new Set<string>();
  const timeline: TimelineItem[] = [];

  for (const tc of toolCalls) {
    // Drop tool calls the backend has already nested inside a group — they
    // render via that group's accordion, not at root level.
    if (tc.tool_call_id && subagentToolCallIds.has(tc.tool_call_id)) continue;

    const msg = (tc.message || "").toLowerCase();
    if (isHandoffCall(tc, msg) || isSpawnCall(tc, msg)) {
      emitGroupForCall(
        tc,
        isHandoffCall(tc, msg),
        allGroups,
        unmatchedSpawned,
        spawnIdxRef,
        timeline,
        emittedGroupIds,
      );
      continue;
    }
    timeline.push({ kind: "tool", data: tc });
  }

  // Surface any backend group whose originating handoff wasn't matched
  // (older chats, race-condition emissions) rather than drop them silently.
  for (const g of finalGroups) {
    if (!emittedGroupIds.has(g.subagent_id)) {
      timeline.push({ kind: "subagent", data: g });
    }
  }

  return timeline;
}

// ── Synthesis fallback for legacy messages ───────────────────────────────────
// For chats persisted before subagent_group backend support was added (pre-2025-04).
// Also handles fast-fail handoffs where _resolve_subagent returns an error
// before subagent_start is ever emitted (so no backend group exists).

function extractSubagentIdFromInputs(
  inputs: ToolCallEntry["inputs"],
): string | undefined {
  if (!inputs || typeof inputs !== "object") return undefined;
  const raw = inputs.subagent_id;
  if (typeof raw !== "string" || !raw) return undefined;
  // Normalize "subagent:posthog" → "posthog" and "posthog_agent" → "posthog"
  // so the icon registry resolves to the integration's logo, not a generic
  // _agent-suffixed key that has no icon entry.
  return raw.replace(/^subagent:/, "").replace(/_agent$/, "");
}

function makeSyntheticHandoffGroup(
  tc: ToolCallEntry,
  index: number,
): EnrichedSubagentGroup {
  const nameMatch = /handing off to (.+)/i.exec(tc.message || "");
  return {
    subagent_id: tc.tool_call_id || `synth-${index}`,
    subagent_name: nameMatch ? nameMatch[1] : "Subagent",
    agent_type: "handoff",
    tool_calls: [],
    duration_ms: null,
    token_count: null,
    started_at: "",
    completed_at: "synthetic",
    icon_url: null,
    tool_category: extractSubagentIdFromInputs(tc.inputs) ?? null,
    nested_subagents: [],
    handoff_input: extractTaskFromInputs(tc.inputs),
    handoff_output: tc.output || undefined,
  };
}

function makeSyntheticSpawnGroup(
  tc: ToolCallEntry,
  index: number,
): EnrichedSubagentGroup {
  return {
    subagent_id: tc.tool_call_id || `synth-spawn-${index}`,
    subagent_name: "Task Agent",
    agent_type: "spawned",
    tool_calls: [],
    duration_ms: null,
    token_count: null,
    started_at: "",
    completed_at: "synthetic",
    icon_url: null,
    tool_category: "spawn_subagent",
    nested_subagents: [],
    handoff_input: extractTaskFromInputs(tc.inputs),
    handoff_output: tc.output || undefined,
  };
}

// Build a timeline directly from a tool-call stream when no backend
// subagent_group entries are present. Handoff/spawn calls become subagent
// timeline items at their natural position; if a handoff returned
// synchronously (output already present, i.e. the fast-fail error path), the
// group is closed immediately so any following executor-level tool calls
// render at root level instead of getting bundled into the failed handoff.
function buildSyntheticTimeline(toolCalls: ToolCallEntry[]): TimelineItem[] {
  const timeline: TimelineItem[] = [];
  let currentGroup: EnrichedSubagentGroup | null = null;
  let synthIdx = 0;

  for (const tc of toolCalls) {
    const msg = (tc.message || "").toLowerCase();

    if (isHandoffCall(tc, msg)) {
      currentGroup = makeSyntheticHandoffGroup(tc, synthIdx++);
      timeline.push({ kind: "subagent", data: currentGroup });
      if (currentGroup.handoff_output) currentGroup = null;
      continue;
    }
    if (isSpawnCall(tc, msg)) {
      const spawnGroup = makeSyntheticSpawnGroup(tc, synthIdx++);
      if (currentGroup) {
        currentGroup.nested_subagents.push(spawnGroup);
      } else {
        timeline.push({ kind: "subagent", data: spawnGroup });
      }
      continue;
    }
    if (currentGroup) {
      currentGroup.tool_calls.push(tc);
    } else {
      timeline.push({ kind: "tool", data: tc });
    }
  }

  // Synthetic groups are built by pushing raw tool calls, so their adjacent
  // reasoning fragments aren't merged yet. Enrich them the same way the backend
  // path does (buildBackendTimeline via deepEnrichGroup) so fallback timelines
  // don't render split Thinking rows.
  return timeline.map((item) =>
    item.kind === "subagent"
      ? { kind: "subagent" as const, data: deepEnrichGroup(item.data) }
      : item,
  );
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export const useSubagentSynthesis = (
  tool_data: ToolDataEntry[] | null | undefined,
): {
  timeline: TimelineItem[];
  processedTools: ToolDataEntry[];
} => {
  return React.useMemo(() => {
    const { groupedEntries, individual, toolCalls, subagentGroups } =
      bucketToolData(tool_data);

    let timeline: TimelineItem[];
    if (subagentGroups.length > 0) {
      timeline = buildBackendTimeline(toolCalls, subagentGroups);
    } else if (toolCalls.length > 0) {
      timeline = buildSyntheticTimeline(toolCalls);
    } else {
      timeline = [];
    }

    return {
      timeline: coalesceTimelineReasoning(timeline),
      processedTools: [...groupedEntries, ...individual],
    };
  }, [tool_data]);
};
