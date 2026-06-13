"use client";

import { Spinner } from "@heroui/spinner";
import { ToolsIcon } from "@icons";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useState } from "react";
import { ChevronDown } from "@/components/shared/icons";
import { CompactMarkdown } from "@/components/ui/CompactMarkdown";
import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import { formatToolName } from "@/features/chat/utils/chatUtils";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { EnrichedSubagentGroup } from "./UnifiedToolThread";

// ── Animation config (matches LoadingIndicator) ─────────────────────────────

const expandTransition = {
  duration: 0.2,
  ease: [0.32, 0.72, 0, 1] as const,
};

// ── Top-level tool call row ─────────────────────────────────────────────────

export function ToolCallRow({
  call,
  isLast,
  getIconUrl,
  getIntegrationName,
}: Readonly<{
  call: ToolCallEntry;
  isLast: boolean;
  getIconUrl: (c: ToolCallEntry) => string | undefined;
  getIntegrationName: (c: ToolCallEntry) => string | undefined;
}>) {
  const [expanded, setExpanded] = useState(false);

  const primaryLabel = call.message || formatToolName(call.tool_name);
  const integrationLabel =
    getIntegrationName(call) ||
    (call.tool_category && call.tool_category !== "unknown"
      ? call.tool_category
          .replaceAll("_", " ")
          .split(" ")
          .map(
            (word) =>
              word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
          )
          .join(" ")
      : "");
  // `show_category === false` means the backend sent a custom/curated label as
  // the primary. In that case the primary already reads naturally, so the
  // secondary shows the raw tool name (with underscores, untrimmed) for
  // transparency. Otherwise the primary IS the tool name, so the secondary shows
  // the integration/category (the original behaviour).
  const hasCustomLabel = call.show_category === false;
  const secondaryLabel = hasCustomLabel
    ? call.tool_name.toLowerCase()
    : integrationLabel;
  // Hide the secondary when it adds nothing — e.g. "retrieve_tools" under
  // "Retrieve tools". Compares with separators stripped so a tool name only
  // shows when it genuinely differs from the primary label.
  const normalize = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const normPrimary = normalize(primaryLabel);
  const normSecondary = normalize(secondaryLabel);
  const hasCategoryText =
    secondaryLabel.length > 0 &&
    normSecondary.length > 0 &&
    !normPrimary.includes(normSecondary) &&
    !normSecondary.includes(normPrimary);
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
        <button
          type="button"
          className={`w-full text-left group/parent ${hasCategoryText ? "min-h-8 flex flex-col justify-center" : "flex items-center min-h-8"} ${hasDetails ? "cursor-pointer" : "cursor-default"}`}
          onClick={() => hasDetails && setExpanded(!expanded)}
        >
          <div className="flex items-center gap-1">
            <p
              className={`text-xs text-zinc-400 font-medium ${hasDetails ? "group-hover/parent:text-white transition-colors" : ""}`}
            >
              {primaryLabel}
            </p>
            {hasDetails && (
              <ChevronDown
                className={`text-zinc-500 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
                width={14}
                height={14}
              />
            )}
          </div>
          {hasCategoryText && (
            <p className="text-[11px] text-zinc-600 leading-tight">
              {secondaryLabel}
            </p>
          )}
        </button>

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

export function SubagentRow({
  group,
  isLast,
  getIconUrl,
  getIntegrationName,
}: Readonly<{
  group: EnrichedSubagentGroup;
  isLast: boolean;
  getIconUrl: (c: ToolCallEntry) => string | undefined;
  getIntegrationName: (c: ToolCallEntry) => string | undefined;
}>) {
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
        <button
          type="button"
          className="min-h-8 flex flex-col justify-center w-full text-left group/sa cursor-pointer"
          onClick={() => setExpanded(!expanded)}
        >
          <div className="flex items-center">
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
          </div>
          <p className="text-[11px] text-zinc-600 leading-tight">
            Subagent
            {visibleToolCalls.length > 0 &&
              ` · ${visibleToolCalls.length} tool${visibleToolCalls.length === 1 ? "" : "s"}`}
          </p>
        </button>

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
