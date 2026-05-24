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

export const useSubagentSynthesis = (
  tool_data: ToolDataEntry[] | null | undefined,
): {
  unifiedToolCalls: ToolCallEntry[];
  unifiedSubagentGroups: EnrichedSubagentGroup[];
  processedTools: ToolDataEntry[];
} => {
  return React.useMemo(() => {
    const grouped = new Map<ToolName, ToolDataMap[ToolName][]>();
    const individual: ToolDataEntry[] = [];
    const toolCalls: ToolCallEntry[] = [];
    const subagentGroups: SubagentGroupData[] = [];

    tool_data?.forEach((entry) => {
      const toolName = entry.tool_name as ToolName;

      // tool_calls_data is handled separately via UnifiedToolThread — excluded from GROUPED_TOOLS and TOOL_RENDERERS
      if (toolName === "tool_calls_data") {
        const calls = Array.isArray(entry.data)
          ? (entry.data as ToolCallEntry[])
          : [entry.data as ToolCallEntry];
        toolCalls.push(...calls);
        return;
      }

      // Collect subagent_group entries
      if (toolName === "subagent_group") {
        subagentGroups.push(entry.data as SubagentGroupData);
        return;
      }

      if (GROUPED_TOOLS.has(toolName)) {
        const bucket = grouped.get(toolName) ?? [];
        bucket.push(entry.data);
        grouped.set(toolName, bucket);
      } else {
        individual.push(entry);
      }
    });

    const groupedEntries: ToolDataEntry[] = Array.from(grouped.entries()).map(
      ([toolName, dataArray]) => ({
        tool_name: toolName,
        tool_category: "",
        data: dataArray as ToolDataMap[ToolName],
        timestamp: null,
      }),
    );

    // If backend provided subagent_group entries, use them.
    // Otherwise, synthesize groups from flat tool calls using
    // "Handing off to X" / "Spawning subagent" as delimiters.
    let finalToolCalls: ToolCallEntry[] = toolCalls;
    let finalGroups: EnrichedSubagentGroup[] = [];

    if (subagentGroups.length > 0) {
      // --- Backend-provided groups: deduplicate + enrich ---
      const subagentToolCallIds = new Set<string>();
      const collectIds = (groups: SubagentGroupData[]) => {
        for (const g of groups) {
          for (const tc of g.tool_calls) {
            if (tc.tool_call_id) subagentToolCallIds.add(tc.tool_call_id);
          }
          collectIds(g.nested_subagents);
        }
      };
      collectIds(subagentGroups);

      finalToolCalls =
        subagentToolCallIds.size > 0
          ? toolCalls.filter(
              (tc) =>
                !tc.tool_call_id || !subagentToolCallIds.has(tc.tool_call_id),
            )
          : toolCalls;

      const deepEnrich = (g: SubagentGroupData): EnrichedSubagentGroup => ({
        ...g,
        nested_subagents: g.nested_subagents.map(deepEnrich),
      });
      finalGroups = subagentGroups.map(deepEnrich);

      // Enrich with input/output from handoff/spawn tool calls
      const allGroups: EnrichedSubagentGroup[] = [];
      const collectAll = (groups: EnrichedSubagentGroup[]) => {
        for (const g of groups) {
          allGroups.push(g);
          collectAll(g.nested_subagents);
        }
      };
      collectAll(finalGroups);

      const remaining: ToolCallEntry[] = [];
      const unmatchedSpawned = allGroups.filter(
        (g) => g.agent_type === "spawned",
      );
      let si = 0;
      for (const tc of finalToolCalls) {
        const msg = (tc.message || "").toLowerCase();
        const isHandoff =
          tc.tool_name === "handoff" || msg.startsWith("handing off to");
        const isSpawn =
          tc.tool_name === "spawn_subagent" || msg === "spawning subagent";
        if (!isHandoff && !isSpawn) {
          remaining.push(tc);
          continue;
        }
        const task =
          tc.inputs && typeof tc.inputs === "object"
            ? (tc.inputs as Record<string, unknown>).task
            : undefined;
        const output = tc.output;
        if (isHandoff) {
          const matched = allGroups.find(
            (g) =>
              g.agent_type === "handoff" &&
              msg.includes(g.subagent_name.toLowerCase()),
          );
          if (matched) {
            if (typeof task === "string" && task) matched.handoff_input = task;
            if (output) matched.handoff_output = output;
          }
        } else if (si < unmatchedSpawned.length) {
          const matched = unmatchedSpawned[si++];
          if (typeof task === "string" && task) matched.handoff_input = task;
          if (output) matched.handoff_output = output;
        }
      }
      finalToolCalls = remaining;

      // Frontend nesting inference: if spawned subagents are at the root level but
      // a handoff group contains a spawn_subagent tool call, nest them inside that group.
      // This handles data saved before parent_subagent_id was propagated correctly.
      const rootSpawned = finalGroups.filter((g) => g.agent_type === "spawned");
      if (rootSpawned.length > 0) {
        let spawnIdx = 0;
        for (const g of finalGroups) {
          if (g.agent_type !== "handoff") continue;
          const hasSpawnCall = g.tool_calls.some(
            (tc) => tc.tool_name === "spawn_subagent",
          );
          if (!hasSpawnCall || spawnIdx >= rootSpawned.length) continue;
          // Move the next unmatched spawned subagent into this group
          const spawned = rootSpawned[spawnIdx++];
          g.nested_subagents.push(spawned as EnrichedSubagentGroup);
        }
        // Remove nested spawned groups from the root list
        const nestedIds = new Set(
          finalGroups
            .filter((g) => g.agent_type === "handoff")
            .flatMap((g) => g.nested_subagents.map((n) => n.subagent_id)),
        );
        finalGroups = finalGroups.filter((g) => !nestedIds.has(g.subagent_id));
      }
    } else if (toolCalls.length > 0) {
      // Synthesis fallback: reconstruct subagent groups from flat tool calls for messages
      // persisted before subagent_group backend support was added (pre-2025-04).
      // Can be removed once all pre-2025-04 messages are no longer surfaced in production.
      // --- No backend groups: synthesize from flat tool calls ---
      // "Handing off to X" starts a handoff group; subsequent tool calls
      // with matching tool_category go into that group.
      // "Spawning subagent" starts a spawned group; subsequent tool calls
      // until next handoff/spawn or end go into that group.
      const topLevel: ToolCallEntry[] = [];
      const syntheticGroups: EnrichedSubagentGroup[] = [];
      let currentGroup: EnrichedSubagentGroup | null = null;

      for (const tc of toolCalls) {
        const msg = (tc.message || "").toLowerCase();
        const isHandoff =
          tc.tool_name === "handoff" || msg.startsWith("handing off to");
        const isSpawn =
          tc.tool_name === "spawn_subagent" || msg === "spawning subagent";

        if (isHandoff) {
          // Close previous group
          if (currentGroup) {
            syntheticGroups.push(currentGroup);
            currentGroup = null;
          }
          // Extract name from "Handing off to {Name}"
          const nameMatch = (tc.message || "").match(/handing off to (.+)/i);
          const name = nameMatch ? nameMatch[1] : "Subagent";
          const task =
            tc.inputs && typeof tc.inputs === "object"
              ? (tc.inputs as Record<string, unknown>).task
              : undefined;
          currentGroup = {
            subagent_id: tc.tool_call_id || `synth-${syntheticGroups.length}`,
            subagent_name: name,
            agent_type: "handoff",
            tool_calls: [],
            duration_ms: null,
            token_count: null,
            started_at: "",
            completed_at: "synthetic",
            icon_url: null,
            tool_category: null,
            nested_subagents: [],
            handoff_input: typeof task === "string" ? task : undefined,
            handoff_output: tc.output || undefined,
          };
        } else if (isSpawn) {
          // Spawned subagent — nest inside current handoff if one is active
          const task =
            tc.inputs && typeof tc.inputs === "object"
              ? (tc.inputs as Record<string, unknown>).task
              : undefined;
          const spawnGroup: EnrichedSubagentGroup = {
            subagent_id:
              tc.tool_call_id || `synth-spawn-${syntheticGroups.length}`,
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
            handoff_input: typeof task === "string" ? task : undefined,
            handoff_output: tc.output || undefined,
          };
          if (currentGroup) {
            currentGroup.nested_subagents.push(spawnGroup);
          } else {
            syntheticGroups.push(spawnGroup);
          }
        } else if (currentGroup) {
          // Tool call belongs to the current group
          currentGroup.tool_calls.push(tc);
        } else {
          topLevel.push(tc);
        }
      }
      if (currentGroup) syntheticGroups.push(currentGroup);

      // Infer tool_category for handoff groups from their tool calls
      for (const g of syntheticGroups) {
        if (g.agent_type === "handoff" && g.tool_calls.length > 0) {
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

      finalToolCalls = topLevel;
      finalGroups = syntheticGroups;
    }

    return {
      unifiedToolCalls: finalToolCalls,
      unifiedSubagentGroups: finalGroups,
      processedTools: [...groupedEntries, ...individual],
    };
  }, [tool_data]);
};
