import React from "react";

import {
  GROUPED_TOOLS,
  type SubagentGroupData,
  type ToolCallEntry,
  type ToolDataEntry,
  type ToolDataMap,
  type ToolName,
} from "@/config/registries/toolRegistry";
import type { EnrichedSubagentGroup } from "../UnifiedToolThread";

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

    if (toolName === "tool_calls_data") {
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

function extractTaskFromInputs(
  inputs: ToolCallEntry["inputs"],
): string | undefined {
  if (!inputs || typeof inputs !== "object") return undefined;
  const task = (inputs as Record<string, unknown>).task;
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

// Walk the tool-call list once; for each handoff/spawn call, find its target
// group and attach handoff_input/output. Return the non-handoff/non-spawn
// tool calls (these render at root level alongside the group cards).
function attachHandoffMetadata(
  finalToolCalls: ToolCallEntry[],
  allGroups: EnrichedSubagentGroup[],
): ToolCallEntry[] {
  const remaining: ToolCallEntry[] = [];
  const unmatchedSpawned = allGroups.filter((g) => g.agent_type === "spawned");
  let spawnIdx = 0;

  for (const tc of finalToolCalls) {
    const msg = (tc.message || "").toLowerCase();
    const handoff = isHandoffCall(tc, msg);
    const spawn = isSpawnCall(tc, msg);
    if (!handoff && !spawn) {
      remaining.push(tc);
      continue;
    }
    const task = extractTaskFromInputs(tc.inputs);
    const output = tc.output || undefined;
    if (handoff) {
      const matched = matchHandoffGroupByName(allGroups, msg);
      if (matched) attachHandoffPayload(matched, task, output);
      continue;
    }
    if (spawnIdx < unmatchedSpawned.length) {
      attachHandoffPayload(unmatchedSpawned[spawnIdx++], task, output);
    }
  }
  return remaining;
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

function enrichBackendSubagentGroups(
  toolCalls: ToolCallEntry[],
  subagentGroups: SubagentGroupData[],
): {
  finalToolCalls: ToolCallEntry[];
  finalGroups: EnrichedSubagentGroup[];
} {
  const subagentToolCallIds = collectAllSubagentToolCallIds(subagentGroups);
  const filtered =
    subagentToolCallIds.size > 0
      ? toolCalls.filter(
          (tc) => !tc.tool_call_id || !subagentToolCallIds.has(tc.tool_call_id),
        )
      : toolCalls;

  let finalGroups = subagentGroups.map(deepEnrichGroup);
  const allGroups = flattenEnrichedGroups(finalGroups);
  const finalToolCalls = attachHandoffMetadata(filtered, allGroups);
  finalGroups = inferNestingForRootSpawned(finalGroups);

  return { finalToolCalls, finalGroups };
}

// ── Synthesis fallback for legacy messages ───────────────────────────────────
// For chats persisted before subagent_group backend support was added (pre-2025-04).
// Can be removed once all such messages are no longer surfaced in production.

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
    tool_category: null,
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

function inferHandoffToolCategory(groups: EnrichedSubagentGroup[]): void {
  for (const g of groups) {
    if (g.agent_type !== "handoff" || g.tool_calls.length === 0) continue;
    const cat = g.tool_calls.find(
      (tc) =>
        tc.tool_category &&
        tc.tool_category !== "unknown" &&
        tc.tool_category !== "plan_tasks" &&
        tc.tool_category !== "retrieve_tools",
    )?.tool_category;
    if (cat) g.tool_category = cat;
  }
}

function synthesizeSubagentGroupsFromCalls(toolCalls: ToolCallEntry[]): {
  finalToolCalls: ToolCallEntry[];
  finalGroups: EnrichedSubagentGroup[];
} {
  const topLevel: ToolCallEntry[] = [];
  const syntheticGroups: EnrichedSubagentGroup[] = [];
  let currentGroup: EnrichedSubagentGroup | null = null;

  for (const tc of toolCalls) {
    const msg = (tc.message || "").toLowerCase();
    if (isHandoffCall(tc, msg)) {
      if (currentGroup) syntheticGroups.push(currentGroup);
      currentGroup = makeSyntheticHandoffGroup(tc, syntheticGroups.length);
      continue;
    }
    if (isSpawnCall(tc, msg)) {
      const spawnGroup = makeSyntheticSpawnGroup(tc, syntheticGroups.length);
      if (currentGroup) {
        currentGroup.nested_subagents.push(spawnGroup);
      } else {
        syntheticGroups.push(spawnGroup);
      }
      continue;
    }
    if (currentGroup) {
      currentGroup.tool_calls.push(tc);
    } else {
      topLevel.push(tc);
    }
  }
  if (currentGroup) syntheticGroups.push(currentGroup);

  inferHandoffToolCategory(syntheticGroups);

  return { finalToolCalls: topLevel, finalGroups: syntheticGroups };
}

// ── Hook ─────────────────────────────────────────────────────────────────────

export const useSubagentSynthesis = (
  tool_data: ToolDataEntry[] | null | undefined,
): {
  unifiedToolCalls: ToolCallEntry[];
  unifiedSubagentGroups: EnrichedSubagentGroup[];
  processedTools: ToolDataEntry[];
} => {
  return React.useMemo(() => {
    const { groupedEntries, individual, toolCalls, subagentGroups } =
      bucketToolData(tool_data);

    let unified: {
      finalToolCalls: ToolCallEntry[];
      finalGroups: EnrichedSubagentGroup[];
    };
    if (subagentGroups.length > 0) {
      unified = enrichBackendSubagentGroups(toolCalls, subagentGroups);
    } else if (toolCalls.length > 0) {
      unified = synthesizeSubagentGroupsFromCalls(toolCalls);
    } else {
      unified = { finalToolCalls: toolCalls, finalGroups: [] };
    }

    return {
      unifiedToolCalls: unified.finalToolCalls,
      unifiedSubagentGroups: unified.finalGroups,
      processedTools: [...groupedEntries, ...individual],
    };
  }, [tool_data]);
};
