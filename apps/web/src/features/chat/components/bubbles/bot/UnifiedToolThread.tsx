"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { Spinner } from "@heroui/spinner";
import { ToolsIcon } from "@icons";
import { AnimatePresence, m } from "motion/react";
import { useCallback, useMemo, useState } from "react";
import { ChevronDown } from "@/components/shared/icons";
import { CompactMarkdown } from "@/components/ui/CompactMarkdown";
import type {
  SubagentGroupData,
  ToolCallEntry,
} from "@/config/registries/toolRegistry";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

/**
 * Unified timeline item — either a regular tool call or a subagent invocation.
 * Items are rendered in a single "Used N tools" collapsible, in order of emission.
 */
/** SubagentGroupData enriched with input/output extracted from the "Handing off" tool call */
export interface EnrichedSubagentGroup extends SubagentGroupData {
  /** Task instruction from the handoff tool call's inputs.task */
  handoff_input?: string;
  /** Result from the handoff tool call's output */
  handoff_output?: string;
}

type TimelineItem =
  | { kind: "tool"; data: ToolCallEntry }
  | { kind: "subagent"; data: EnrichedSubagentGroup };

interface UnifiedToolThreadProps {
  /** Top-level (non-subagent) tool calls */
  tool_calls: ToolCallEntry[];
  /** Subagent groups (handoff + spawned), enriched with input/output */
  subagent_groups: EnrichedSubagentGroup[];
}

// ── Animation config (matches LoadingIndicator) ─────────────────────────────

const expandTransition = {
  duration: 0.2,
  ease: [0.32, 0.72, 0, 1] as const,
};

const SHOW_ICONS = 10;

// ── Component ───────────────────────────────────────────────────────────────

export default function UnifiedToolThread({
  tool_calls,
  subagent_groups,
}: UnifiedToolThreadProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { integrations } = useIntegrations();

  const integrationLookup = useMemo(() => {
    const lookup = new Map<string, { iconUrl?: string; name?: string }>();
    for (const int of integrations) {
      if (int.id) lookup.set(int.id, { iconUrl: int.iconUrl, name: int.name });
    }
    return lookup;
  }, [integrations]);

  const getIconUrl = useCallback(
    (call: ToolCallEntry): string | undefined => {
      if (call.icon_url) return call.icon_url;
      return integrationLookup.get(call.tool_category)?.iconUrl;
    },
    [integrationLookup],
  );

  const getIntegrationName = useCallback(
    (call: ToolCallEntry): string | undefined => {
      if (call.integration_name) return call.integration_name;
      return integrationLookup.get(call.tool_category)?.name;
    },
    [integrationLookup],
  );

  // Build interleaved timeline — tools first, then subagents (matching emission order)
  const timeline = useMemo<TimelineItem[]>(() => {
    const items: TimelineItem[] = [];
    for (const tc of tool_calls) {
      items.push({ kind: "tool", data: tc });
    }
    for (const sg of subagent_groups) {
      items.push({ kind: "subagent", data: sg });
    }
    return items;
  }, [tool_calls, subagent_groups]);

  // Total tool count (top-level + all subagent tool calls)
  const totalToolCount = useMemo(() => {
    let count = tool_calls.length;
    const countSubagent = (sg: EnrichedSubagentGroup): number => {
      let n = sg.tool_calls.length;
      for (const nested of sg.nested_subagents) n += countSubagent(nested);
      return n;
    };
    for (const sg of subagent_groups) count += countSubagent(sg);
    return count;
  }, [tool_calls, subagent_groups]);

  // Stacked icons — deduplicated by category across all items
  const stackedIcons = useMemo(() => {
    const seenCategories = new Set<string>();
    const uniqueIcons: { category: string; iconUrl?: string }[] = [];

    for (const item of timeline) {
      const cat =
        item.kind === "tool"
          ? item.data.tool_category || "general"
          : item.data.tool_category || "subagent";
      if (seenCategories.has(cat)) continue;
      seenCategories.add(cat);
      uniqueIcons.push({
        category: cat,
        iconUrl:
          item.kind === "tool"
            ? getIconUrl(item.data)
            : (item.data.icon_url ?? undefined),
      });
    }

    const display = uniqueIcons.slice(0, SHOW_ICONS);
    if (display.length === 0) return null;

    return (
      <div className="flex min-h-8 items-center -space-x-2">
        {display.map((d, i) => {
          const icon = getToolCategoryIcon(
            d.category,
            { width: 21, height: 21 },
            d.iconUrl,
          ) || (
            <div className="p-1 bg-zinc-800 rounded-lg text-zinc-400 backdrop-blur">
              <ToolsIcon width={21} height={21} />
            </div>
          );
          return (
            <div
              key={`${d.category}-${i}`}
              className="relative flex min-w-8 items-center justify-center"
              style={{
                rotate:
                  display.length > 1
                    ? i % 2 === 0
                      ? "8deg"
                      : "-8deg"
                    : "0deg",
                zIndex: i,
              }}
            >
              {icon}
            </div>
          );
        })}
        {uniqueIcons.length > SHOW_ICONS && (
          <div className="z-0 flex size-7 min-h-7 min-w-7 items-center justify-center rounded-lg bg-zinc-700/60 text-xs text-foreground-500 font-normal">
            +{uniqueIcons.length - SHOW_ICONS}
          </div>
        )}
      </div>
    );
  }, [timeline, integrationLookup, getIconUrl]);

  if (timeline.length === 0) return null;

  return (
    <div className="w-fit max-w-140">
      <Accordion
        variant="light"
        isCompact
        hideIndicator
        selectedKeys={isExpanded ? ["tools"] : []}
        onSelectionChange={(keys) => {
          setIsExpanded(
            keys === "all" || (keys instanceof Set && keys.has("tools")),
          );
        }}
        style={{ padding: 0 }}
        itemClasses={{ trigger: "cursor-pointer py-0" }}
      >
        <AccordionItem
          key="tools"
          title={
            <div className="flex items-center hover:text-white text-zinc-500">
              {stackedIcons}
              <span className="text-xs font-medium transition-colors duration-200">
                Used {totalToolCount} tool
                {totalToolCount !== 1 ? "s" : ""}
              </span>
              <ChevronDown
                className={`${isExpanded ? "rotate-180" : ""} ml-2 transition-transform duration-200`}
                width={18}
                height={18}
              />
            </div>
          }
        >
          <div className="py-2">
            {timeline.map((item, idx) => {
              const isLast = idx === timeline.length - 1;

              if (item.kind === "tool") {
                return (
                  <ToolCallRow
                    key={`tc-${item.data.tool_call_id || idx}`}
                    call={item.data}
                    isLast={isLast}
                    getIconUrl={getIconUrl}
                    getIntegrationName={getIntegrationName}
                  />
                );
              }

              return (
                <SubagentRow
                  key={`sa-${item.data.subagent_id}`}
                  group={item.data}
                  isLast={isLast}
                  getIconUrl={getIconUrl}
                  getIntegrationName={getIntegrationName}
                />
              );
            })}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

// ── Top-level tool call row ─────────────────────────────────────────────────

function ToolCallRow({
  call,
  isLast,
  getIconUrl,
  getIntegrationName,
}: {
  call: ToolCallEntry;
  isLast: boolean;
  getIconUrl: (c: ToolCallEntry) => string | undefined;
  getIntegrationName: (c: ToolCallEntry) => string | undefined;
}) {
  const [expanded, setExpanded] = useState(false);

  const hasCategoryText =
    call.show_category !== false &&
    call.tool_category &&
    call.tool_category !== "unknown";
  const hasInputs =
    call.inputs &&
    typeof call.inputs === "object" &&
    Object.keys(call.inputs).length > 0;
  const hasOutput = call.output && call.output.trim().length > 0;
  const hasDetails = hasInputs || hasOutput;

  return (
    <div className="flex items-stretch gap-2">
      <div className="flex flex-col items-center self-stretch">
        <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
          {getToolCategoryIcon(
            call.tool_category || "general",
            { size: 21, width: 21, height: 21 },
            getIconUrl(call),
          ) || (
            <div className="p-1 bg-zinc-800 rounded-lg">
              <ToolsIcon width={21} height={21} />
            </div>
          )}
        </div>
        {!isLast && <div className="w-px flex-1 bg-default-200 min-h-4" />}
      </div>

      <div className="flex-1 min-w-0">
        <div
          className={`${hasCategoryText ? "min-h-8 flex flex-col justify-center" : "flex items-center min-h-8"}`}
        >
          <button
            type="button"
            className={`flex items-center gap-1 group/parent ${hasDetails ? "cursor-pointer" : ""}`}
            onClick={() => hasDetails && setExpanded(!expanded)}
          >
            <p
              className={`text-xs text-zinc-400 font-medium ${hasDetails ? "group-hover/parent:text-white transition-colors" : ""}`}
            >
              {call.message || formatToolName(call.tool_name)}
            </p>
            {hasDetails && (
              <ChevronDown
                className={`text-zinc-500 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
                width={14}
                height={14}
              />
            )}
          </button>
          {hasCategoryText && (
            <p className="text-[11px] text-default-400 capitalize leading-tight">
              {getIntegrationName(call) ||
                call.tool_category
                  .replace(/_/g, " ")
                  .split(" ")
                  .map(
                    (word) =>
                      word.charAt(0).toUpperCase() +
                      word.slice(1).toLowerCase(),
                  )
                  .join(" ")}
            </p>
          )}
        </div>

        <AnimatePresence>
          {expanded && hasDetails && (
            <m.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={expandTransition}
              className="overflow-hidden"
            >
              <div className="mt-2 space-y-2 text-[11px] bg-zinc-800/50 rounded-xl p-3 mb-3 w-fit">
                {hasInputs && (
                  <div className="flex flex-col">
                    <span className="text-zinc-500 font-medium mb-1">
                      Input
                    </span>
                    <CompactMarkdown content={call.inputs} />
                  </div>
                )}
                {hasOutput && (
                  <div className="flex flex-col">
                    <span className="text-zinc-500 font-medium mb-1">
                      Output
                    </span>
                    <CompactMarkdown content={call.output} />
                  </div>
                )}
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

// ── Subagent row (Option B style) ───────────────────────────────────────────

function SubagentRow({
  group,
  isLast,
  getIconUrl,
  getIntegrationName,
}: {
  group: EnrichedSubagentGroup;
  isLast: boolean;
  getIconUrl: (c: ToolCallEntry) => string | undefined;
  getIntegrationName: (c: ToolCallEntry) => string | undefined;
}) {
  // Start expanded while running so live tool calls are visible by default
  const [expanded, setExpanded] = useState(() => group.completed_at === null);
  const isRunning = group.completed_at === null;

  // Filter out spawn_subagent tool calls — they're represented by nested SubagentRows
  const visibleToolCalls = group.tool_calls.filter(
    (tc) => tc.tool_name !== "spawn_subagent",
  );

  const iconEl = getToolCategoryIcon(
    group.tool_category ?? "subagent",
    { width: 21, height: 21 },
    group.icon_url ?? undefined,
  ) || (
    <div className="p-1 bg-zinc-800 rounded-lg">
      <ToolsIcon width={21} height={21} />
    </div>
  );

  // Running mode: show spinner + live tool calls, collapsible
  if (isRunning) {
    return (
      <div className="flex items-stretch gap-2">
        <div className="flex flex-col items-center self-stretch">
          <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
            {iconEl}
          </div>
          {!isLast && <div className="w-px flex-1 bg-default-200 min-h-4" />}
        </div>
        <div className="flex-1 min-w-0">
          <button
            type="button"
            className="min-h-8 flex items-center gap-2 cursor-pointer w-full group/sa"
            onClick={() => setExpanded((e) => !e)}
          >
            <span className="text-xs font-medium text-zinc-400 group-hover/sa:text-zinc-300 transition-colors mr-auto">
              {group.subagent_name}
            </span>
            <Spinner size="sm" color="default" />
            <ChevronDown
              className={`text-zinc-600 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
              width={14}
              height={14}
            />
          </button>
          {expanded && visibleToolCalls.length > 0 && (
            <div className="mt-1 space-y-0">
              {visibleToolCalls.map((tc, tIdx) => (
                <ToolCallRow
                  key={`${group.subagent_id}-live-${tc.tool_call_id || tIdx}`}
                  call={tc}
                  isLast={tIdx === visibleToolCalls.length - 1}
                  getIconUrl={getIconUrl}
                  getIntegrationName={getIntegrationName}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  // Completed mode: show duration + collapsed/expanded tool history
  return (
    <div className="flex items-stretch gap-2">
      <div className="flex flex-col items-center self-stretch">
        <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
          {iconEl}
        </div>
        {!isLast && <div className="w-px flex-1 bg-default-200 min-h-4" />}
      </div>

      <div className="flex-1 min-w-0">
        <div className="min-h-8 flex flex-col justify-center">
          <button
            type="button"
            className="flex items-center group/sa cursor-pointer w-full"
            onClick={() => setExpanded(!expanded)}
          >
            <span className="text-xs font-medium text-zinc-200 group-hover/sa:text-white transition-colors mr-auto">
              {group.subagent_name}
            </span>
            <div className="flex items-center gap-1 ml-4 shrink-0">
              {group.duration_ms != null && (
                <span className="text-[10px] text-zinc-600 tabular-nums">
                  {(group.duration_ms / 1000).toFixed(1)}s
                </span>
              )}
              <ChevronDown
                className={`text-zinc-600 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
                width={14}
                height={14}
              />
            </div>
          </button>
          <p className="text-[11px] text-zinc-600 leading-tight">
            Subagent
            {visibleToolCalls.length > 0 &&
              ` · ${visibleToolCalls.length} tool${visibleToolCalls.length !== 1 ? "s" : ""}`}
          </p>
        </div>

        <AnimatePresence>
          {expanded && (
            <m.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={expandTransition}
              className="overflow-hidden"
            >
              <div className="mt-1.5 mb-1">
                {group.handoff_input && (
                  <div className="mb-2 text-[11px] bg-zinc-800/50 rounded-xl p-3 w-fit">
                    <span className="text-zinc-500 font-medium mb-0.5 block">
                      Task
                    </span>
                    <CompactMarkdown content={group.handoff_input} />
                  </div>
                )}

                {visibleToolCalls.length > 0 && (
                  <div className="space-y-0">
                    {visibleToolCalls.map((tc, tIdx) => (
                      <ToolCallRow
                        key={`${group.subagent_id}-tc-${tc.tool_call_id || tIdx}`}
                        call={tc}
                        isLast={
                          tIdx === visibleToolCalls.length - 1 &&
                          group.nested_subagents.length === 0
                        }
                        getIconUrl={getIconUrl}
                        getIntegrationName={getIntegrationName}
                      />
                    ))}
                  </div>
                )}

                {group.nested_subagents.length > 0 && (
                  <div className={visibleToolCalls.length > 0 ? "mt-1" : ""}>
                    {group.nested_subagents.map((nested) => (
                      <SubagentRow
                        key={`nested-${nested.subagent_id}`}
                        group={nested}
                        isLast
                        getIconUrl={getIconUrl}
                        getIntegrationName={getIntegrationName}
                      />
                    ))}
                  </div>
                )}

                {group.handoff_output && (
                  <div className="mt-2 text-[11px] bg-zinc-800/50 rounded-xl p-3 w-fit">
                    <span className="text-zinc-500 font-medium mb-0.5 block">
                      Result
                    </span>
                    <CompactMarkdown content={group.handoff_output} />
                  </div>
                )}
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
