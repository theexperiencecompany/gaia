"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import { ToolsIcon } from "@icons";
import type { ApprovalStatus } from "@shared/chat";
import { useCallback, useMemo, useState } from "react";
import { ChevronDown } from "@/components/shared/icons";
import type {
  SubagentGroupData,
  ToolCallEntry,
} from "@/config/registries/toolRegistry";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrationLookup } from "@/features/integrations/hooks/useIntegrationLookup";
import { StepRow, SubagentRow } from "./SubagentRow";
import { deriveTimelineItemKeys } from "./TextBubble/useSubagentSynthesis";

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
  /** Whether the owning message's stream is still open — gates subagent
   *  spinners so a dropped/missing end event can't spin a card forever. */
  isStreaming: boolean;
  /** tool_call_ids currently blocked on a HIL approval — the matching row shows
   *  "Waiting for approval" instead of a running spinner. */
  pendingApprovalToolCallIds: Set<string>;
  /** Settled decisions keyed by tool_call_id — the row carries the outcome chip. */
  approvalStatusByToolCallId: Map<string, ApprovalStatus>;
}

const SHOW_ICONS = 10;

// ── Stacked category icons ──────────────────────────────────────────────────

// Rendered as a child after UnifiedToolThread's early return, so renders that
// bail out never build this subtree.
function StackedIcons({
  icons,
}: {
  icons: { category: string; iconUrl?: string }[];
}) {
  const display = icons.slice(0, SHOW_ICONS);
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
        let rotate = "0deg";
        if (display.length > 1) {
          rotate = i % 2 === 0 ? "8deg" : "-8deg";
        }
        return (
          <div
            key={d.category}
            className="relative flex min-w-8 items-center justify-center"
            style={{
              rotate,
              zIndex: i,
            }}
          >
            {icon}
          </div>
        );
      })}
      {icons.length > SHOW_ICONS && (
        <div className="z-0 flex size-7 min-h-7 min-w-7 items-center justify-center rounded-lg bg-zinc-700/60 text-xs text-foreground-500 font-normal">
          +{icons.length - SHOW_ICONS}
        </div>
      )}
    </div>
  );
}

// ── Stable keys for streamed entries ────────────────────────────────────────

// Root timeline items get one stable React key each, derived from stream-
// stable structure (tool_call_id / subagent_id / anchored slot — never payload
// content) by deriveTimelineItemKeys in ./TextBubble/useSubagentSynthesis. A
// growing reasoning delta therefore keeps its key across every stream frame
// instead of remounting its Thinking row (which would snap `expanded` shut).

// ── Component ───────────────────────────────────────────────────────────────

export default function UnifiedToolThread({
  timeline,
  isStreaming,
  pendingApprovalToolCallIds,
  approvalStatusByToolCallId,
}: Readonly<UnifiedToolThreadProps>) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { getIntegrationName: lookupName, getIntegrationIconUrl } =
    useIntegrationLookup();

  const getIconUrl = useCallback(
    (call: ToolCallEntry): string | undefined => {
      if (call.icon_url) return call.icon_url;
      return getIntegrationIconUrl(call.tool_category);
    },
    [getIntegrationIconUrl],
  );

  const getIntegrationName = useCallback(
    (call: ToolCallEntry): string | undefined => {
      if (call.integration_name) return call.integration_name;
      return lookupName(call.tool_category);
    },
    [lookupName],
  );

  // Total tool count (root-level + all nested subagent tool calls)
  const totalToolCount = useMemo(() => {
    // Thinking steps (entries carrying `reasoning`) are not tools — exclude them
    // from the "Used N tools" count.
    const countSubagent = (sg: EnrichedSubagentGroup): number => {
      // spawn_subagent steps are hidden by SubagentRow (they render as nested
      // rows), so exclude them here too or the total overcounts what's shown.
      let n = sg.tool_calls.filter(
        (tc) => tc.reasoning == null && tc.tool_name !== "spawn_subagent",
      ).length;
      for (const nested of sg.nested_subagents) n += countSubagent(nested);
      return n;
    };
    let count = 0;
    for (const item of timeline) {
      if (item.kind === "tool") {
        if (item.data.reasoning == null) count += 1;
      } else {
        count += countSubagent(item.data);
      }
    }
    return count;
  }, [timeline]);

  // Stacked icons — deduplicated by category across all items. Data only; the
  // JSX subtree lives in <StackedIcons>, rendered after the early return.
  const uniqueIcons = useMemo(() => {
    const seenCategories = new Set<string>();
    const icons: { category: string; iconUrl?: string }[] = [];

    for (const item of timeline) {
      // Thinking steps have no tool icon — keep them out of the stacked icons.
      if (item.kind === "tool" && item.data.reasoning != null) continue;
      const cat =
        item.kind === "tool"
          ? item.data.tool_category || "general"
          : item.data.tool_category || "subagent";
      if (seenCategories.has(cat)) continue;
      seenCategories.add(cat);
      icons.push({
        category: cat,
        iconUrl:
          item.kind === "tool"
            ? getIconUrl(item.data)
            : (item.data.icon_url ?? undefined),
      });
    }

    return icons;
  }, [timeline, getIconUrl]);

  // One stable React key per timeline item — derived from stream-stable
  // structure (tool_call_id / subagent_id / anchored slot), never payload
  // content, so a growing reasoning delta keeps its row's identity and its
  // `expanded` state across every stream frame.
  const itemKeys = deriveTimelineItemKeys(timeline);

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
              {totalToolCount > 1 && <StackedIcons icons={uniqueIcons} />}
              <span
                className={`text-xs font-medium transition-colors duration-200 ${totalToolCount > 1 ? "ml-2" : ""}`}
              >
                Used {totalToolCount} tool
                {totalToolCount === 1 ? "" : "s"}
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
                  <StepRow
                    key={itemKeys[idx]}
                    call={item.data}
                    isLast={isLast}
                    getIconUrl={getIconUrl}
                    getIntegrationName={getIntegrationName}
                    pendingApprovalToolCallIds={pendingApprovalToolCallIds}
                    approvalStatusByToolCallId={approvalStatusByToolCallId}
                  />
                );
              }

              return (
                <SubagentRow
                  key={itemKeys[idx]}
                  group={item.data}
                  isLast={isLast}
                  isStreaming={isStreaming}
                  getIconUrl={getIconUrl}
                  getIntegrationName={getIntegrationName}
                  pendingApprovalToolCallIds={pendingApprovalToolCallIds}
                  approvalStatusByToolCallId={approvalStatusByToolCallId}
                />
              );
            })}
          </div>
        </AccordionItem>
      </Accordion>
    </div>
  );
}
