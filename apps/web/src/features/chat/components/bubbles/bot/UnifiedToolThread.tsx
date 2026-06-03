"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { ToolsIcon } from "@icons";
import { useCallback, useMemo, useState } from "react";
import { ChevronDown } from "@/components/shared/icons";
import type {
  SubagentGroupData,
  ToolCallEntry,
} from "@/config/registries/toolRegistry";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { SubagentRow, ToolCallRow } from "./SubagentRow";

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

export type TimelineItem =
  | { kind: "tool"; data: ToolCallEntry }
  | { kind: "subagent"; data: EnrichedSubagentGroup };

interface UnifiedToolThreadProps {
  /** Ordered timeline of tool calls and subagent groups, in emission order. */
  timeline: TimelineItem[];
}

const SHOW_ICONS = 10;

// ── Component ───────────────────────────────────────────────────────────────

export default function UnifiedToolThread({
  timeline,
}: Readonly<UnifiedToolThreadProps>) {
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

  // Total tool count (root-level + all nested subagent tool calls)
  const totalToolCount = useMemo(() => {
    const countSubagent = (sg: EnrichedSubagentGroup): number => {
      let n = sg.tool_calls.length;
      for (const nested of sg.nested_subagents) n += countSubagent(nested);
      return n;
    };
    let count = 0;
    for (const item of timeline) {
      count += item.kind === "tool" ? 1 : countSubagent(item.data);
    }
    return count;
  }, [timeline]);

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
  }, [timeline, getIconUrl]);

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
              {totalToolCount > 1 && stackedIcons}
              <span
                className={`text-xs font-medium transition-colors duration-200 ${totalToolCount > 1 ? "ml-2" : ""}`}
              >
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
