"use client";

import React from "react";
import type { SubagentGroupData } from "@/config/registries/toolRegistry";
import ToolCallsSection from "./ToolCallsSection";

interface SubagentThreadProps {
  group: SubagentGroupData;
}

/**
 * Renders an Option-B style "thread" block for a single subagent invocation.
 *
 * Shows a bordered box with:
 *   - Header: icon · name · type badge · running indicator or (duration + tokens)
 *   - Body: the subagent's tool calls via ToolCallsSection (reused as-is)
 *
 * Color scheme:
 *   - Purple border / tint → handoff subagents (integration agents)
 *   - Blue border / tint  → spawned subagents (lightweight task agents)
 */
export function SubagentThread({ group }: SubagentThreadProps) {
  const isRunning = group.completed_at === null;
  const isHandoff = group.agent_type === "handoff";

  const containerCls = isHandoff
    ? "border-purple-900/40 bg-purple-950/10"
    : "border-blue-900/40 bg-blue-950/10";

  const nameCls = isHandoff ? "text-purple-300" : "text-blue-300";

  const badgeCls = isHandoff
    ? "bg-purple-900/60 text-purple-300"
    : "bg-blue-900/60 text-blue-300";

  const badgeLabel = isHandoff ? "Subagent" : "Spawned";

  const icon = isHandoff ? "↗" : "⚡";

  const durationLabel =
    group.duration_ms !== null
      ? `${(group.duration_ms / 1000).toFixed(1)}s`
      : null;

  const tokenLabel =
    group.token_count !== null
      ? `${group.token_count.toLocaleString()} tok`
      : null;

  return (
    <div
      className={`rounded-xl border overflow-hidden my-1.5 ${containerCls}`}
    >
      {/* Header */}
      <div
        className={`flex items-center gap-2 px-3 py-2 border-b ${
          isHandoff ? "border-purple-900/30" : "border-blue-900/30"
        }`}
      >
        <span className="text-sm leading-none">{icon}</span>
        <span className={`text-xs font-semibold ${nameCls}`}>
          {group.subagent_name}
        </span>
        <span
          className={`text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded ${badgeCls}`}
        >
          {badgeLabel}
        </span>

        <div className="ml-auto flex items-center gap-2 text-[11px] text-zinc-500">
          {isRunning ? (
            <span className="animate-pulse">Running…</span>
          ) : (
            <>
              {durationLabel && <span>⏱ {durationLabel}</span>}
              {tokenLabel && <span>⚡ {tokenLabel}</span>}
            </>
          )}
        </div>
      </div>

      {/* Tool calls body — reuse existing ToolCallsSection */}
      {group.tool_calls.length > 0 && (
        <div className="px-2 py-1.5">
          <ToolCallsSection tool_calls_data={group.tool_calls} />
        </div>
      )}
    </div>
  );
}

export default SubagentThread;
