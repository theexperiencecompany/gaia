"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Brain02Icon, ZapIcon } from "@icons";
import { m } from "motion/react";
import { useState } from "react";
import { ChevronDown } from "@/components/shared/icons";
import type { SubagentGroupData } from "@/config/registries/toolRegistry";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import ToolCallsSection from "./ToolCallsSection";

interface SubagentThreadProps {
  group: SubagentGroupData;
}

/**
 * Renders a subagent invocation as a timeline entry consistent with ToolCallsSection.
 *
 * Visual language matches the rest of the tool call UI:
 *   - Same Accordion pattern, zinc colors, compact typography
 *   - Icon column with the same rounded-lg + colored bg wrapper
 *   - Indented body with left connector line (matches ToolCallsSection items)
 */
export function SubagentThread({ group }: SubagentThreadProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const isRunning = group.completed_at === null;
  const isHandoff = group.agent_type === "handoff";
  const typeLabel = isHandoff ? "Subagent" : "Spawned";

  const iconNode = isHandoff
    ? (getToolCategoryIcon(
        group.tool_category ?? "subagent",
        { width: 21, height: 21 },
        group.icon_url ?? undefined,
      ) ?? (
        <div className="relative rounded-lg p-1">
          <m.div className="absolute inset-0 rounded-lg bg-violet-900/50" />
          <div className="relative">
            <Brain02Icon width={21} height={21} className="text-violet-400" />
          </div>
        </div>
      ))
    : (
      <div className="relative rounded-lg p-1">
        <m.div className="absolute inset-0 rounded-lg bg-zinc-700" />
        <div className="relative">
          <ZapIcon width={21} height={21} className="text-zinc-400" />
        </div>
      </div>
    );

  const durationLabel =
    group.duration_ms !== null
      ? `${(group.duration_ms / 1000).toFixed(1)}s`
      : null;

  return (
    <div className="w-fit max-w-140">
      <Accordion
        variant="light"
        isCompact
        hideIndicator
        selectedKeys={isExpanded ? ["thread"] : []}
        onSelectionChange={(keys) => {
          const expanded =
            keys === "all" || (keys instanceof Set && keys.has("thread"));
          setIsExpanded(expanded);
        }}
        style={{ padding: 0 }}
        itemClasses={{ trigger: "cursor-pointer py-0" }}
      >
        <AccordionItem
          key="thread"
          title={
            <div className="flex w-full items-center hover:text-white text-zinc-500">
              {/* Icon — same wrapper as ToolCallsSection items */}
              <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
                {iconNode}
              </div>

              {/* Name + type label */}
              <div className="ml-2 flex min-w-0 flex-col">
                <span className="text-xs font-medium transition-all duration-200">
                  {group.subagent_name}
                </span>
                <span className="text-[11px] text-default-400">{typeLabel}</span>
              </div>

              <ChevronDown
                className={`${isExpanded ? "rotate-180" : ""} ml-2 shrink-0 transition-all duration-200`}
                width={18}
                height={18}
              />

              {/* Duration / running state */}
              <div className="ml-auto pl-3 text-[11px] text-zinc-600 shrink-0">
                {isRunning ? (
                  <span className="animate-pulse">running…</span>
                ) : (
                  durationLabel && <span>{durationLabel}</span>
                )}
              </div>
            </div>
          }
        >
          {/* Indented body — left line mirrors the connector lines in ToolCallsSection */}
          <div className="ml-4 border-l border-default-100 pl-6 py-1">
            {group.tool_calls.length > 0 && (
              <ToolCallsSection tool_calls_data={group.tool_calls} />
            )}
            {group.nested_subagents.length > 0 && (
              <div className={group.tool_calls.length > 0 ? "mt-3" : ""}>
                {group.nested_subagents.map((nested) => (
                  <SubagentThread key={nested.subagent_id} group={nested} />
                ))}
              </div>
            )}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

export default SubagentThread;
