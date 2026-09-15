"use client";

import { Spinner } from "@heroui/spinner";
import { ToolsIcon } from "@icons";
import type { ApprovalStatus } from "@shared/chat";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useState } from "react";
import { BrainIcon, ChevronDown } from "@/components/shared/icons";
import { CompactMarkdown } from "@/components/ui/CompactMarkdown";
import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { deriveStepKeys } from "./TextBubble/useSubagentSynthesis";
import { ToolCallRow, WaitingForApprovalPill } from "./ToolCallRow";
import { expandTransition } from "./toolCallDisplay";
import type { EnrichedSubagentGroup } from "./UnifiedToolThread";

// A step where the model reasoned (ToolCallEntry carrying `reasoning`).
// Mirrors ToolCallRow's layout so thinking sits naturally between tool steps.
function ThinkingStepRow({
  reasoning,
  isLast,
}: Readonly<{ reasoning: string; isLast: boolean }>) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="flex items-stretch gap-2">
      <div className="flex flex-col items-center self-stretch">
        <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
          <BrainIcon width={21} height={21} className="text-zinc-500" />
        </div>
        {!isLast && <div className="w-px flex-1 bg-default-200 min-h-4" />}
      </div>

      <div className="flex-1 min-w-0">
        <button
          type="button"
          className="w-full text-left group/think flex items-center min-h-8 cursor-pointer"
          onClick={() => setExpanded((e) => !e)}
        >
          <div className="flex items-center gap-1">
            <p className="text-xs font-medium text-zinc-500 italic group-hover/think:text-zinc-300 transition-colors">
              Thinking
            </p>
            <ChevronDown
              className={`text-zinc-600 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
              width={14}
              height={14}
            />
          </div>
        </button>

        <AnimatePresence>
          {expanded && (
            <m.div
              layout
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={expandTransition}
              className="overflow-hidden"
            >
              <div className="mt-2 mb-3 w-fit rounded-xl bg-zinc-800/50 p-3 text-[11px] text-zinc-400">
                <CompactMarkdown content={reasoning} />
              </div>
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

interface StepCallbacks {
  getIconUrl: (c: ToolCallEntry) => string | undefined;
  getIntegrationName: (c: ToolCallEntry) => string | undefined;
  /** tool_call_ids blocked on a pending HIL approval. */
  pendingApprovalToolCallIds: Set<string>;
  approvalStatusByToolCallId?: Map<string, ApprovalStatus>;
}

// One timeline step: a thinking block when the entry carries `reasoning`, else a
// tool-call row. Hook-free, so it avoids conditional-hook issues at every call site.
export function StepRow(
  props: Readonly<StepCallbacks & { call: ToolCallEntry; isLast: boolean }>,
) {
  const {
    pendingApprovalToolCallIds,
    approvalStatusByToolCallId,
    ...rowProps
  } = props;
  if (props.call.reasoning != null) {
    return (
      <ThinkingStepRow reasoning={props.call.reasoning} isLast={props.isLast} />
    );
  }
  const awaitingApproval =
    !!props.call.tool_call_id &&
    pendingApprovalToolCallIds.has(props.call.tool_call_id);
  const approvalStatus = props.call.tool_call_id
    ? approvalStatusByToolCallId?.get(props.call.tool_call_id)
    : undefined;
  return (
    <ToolCallRow
      {...rowProps}
      awaitingApproval={awaitingApproval}
      approvalStatus={approvalStatus}
    />
  );
}

function deriveSubagentSteps(
  group: EnrichedSubagentGroup,
  pendingApprovalToolCallIds: Set<string>,
) {
  // spawn_subagent is excluded here; it renders as nested SubagentRows.
  const visibleSteps = group.tool_calls.filter(
    (tc) => tc.tool_name !== "spawn_subagent",
  );
  return {
    visibleSteps,
    // Keys come from stream-stable structure, never payload, so a growing reasoning delta keeps its `expanded` state.
    stepKeys: deriveStepKeys(group.subagent_id, visibleSteps),
    awaitingApproval: visibleSteps.some(
      (tc) =>
        !!tc.tool_call_id && pendingApprovalToolCallIds.has(tc.tool_call_id),
    ),
    // Thinking blocks aren't "tools".
    toolCount: visibleSteps.filter((s) => s.reasoning == null).length,
  };
}

function SubagentIcon({ group }: Readonly<{ group: EnrichedSubagentGroup }>) {
  return (
    getToolCategoryIcon(
      group.tool_category ?? "subagent",
      { width: 21, height: 21 },
      group.icon_url ?? undefined,
    ) || (
      <div className="p-1 bg-zinc-800 rounded-lg">
        <ToolsIcon width={21} height={21} />
      </div>
    )
  );
}

function SubagentTextBlock({
  title,
  content,
  className,
}: Readonly<{ title: string; content: string; className: string }>) {
  return (
    <div
      className={`${className} text-[11px] bg-zinc-800/50 rounded-xl p-3 w-fit`}
    >
      <span className="text-zinc-500 font-medium mb-0.5 block">{title}</span>
      <CompactMarkdown content={content} />
    </div>
  );
}

function SubagentStepList({
  steps,
  stepKeys,
  lastIsTerminal,
  callbacks,
}: Readonly<{
  steps: ToolCallEntry[];
  stepKeys: string[];
  /** False when nested subagents follow the last step, so its connector continues. */
  lastIsTerminal: boolean;
  callbacks: StepCallbacks;
}>) {
  if (steps.length === 0) return null;
  return (
    <div className="space-y-0">
      {steps.map((tc, tIdx) => (
        <StepRow
          key={stepKeys[tIdx]}
          call={tc}
          isLast={tIdx === steps.length - 1 && lastIsTerminal}
          {...callbacks}
        />
      ))}
    </div>
  );
}

interface SubagentBodyProps {
  group: EnrichedSubagentGroup;
  expanded: boolean;
  onToggle: () => void;
  steps: ReturnType<typeof deriveSubagentSteps>;
  isStreaming: boolean;
  callbacks: StepCallbacks;
}

function RunningSubagentBody({
  group,
  expanded,
  onToggle,
  steps,
  callbacks,
}: Readonly<SubagentBodyProps>) {
  return (
    <>
      <button
        type="button"
        className="min-h-8 flex items-center gap-2 cursor-pointer w-full group/sa"
        onClick={onToggle}
      >
        <span className="text-xs font-medium text-zinc-400 group-hover/sa:text-zinc-300 transition-colors mr-auto">
          {group.subagent_name}
        </span>
        {steps.awaitingApproval ? (
          <WaitingForApprovalPill />
        ) : (
          <Spinner size="sm" color="default" />
        )}
        <ChevronDown
          className={`text-zinc-600 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
          width={14}
          height={14}
        />
      </button>
      {expanded && (
        <div className="mt-1">
          {/* The task is known at spawn time, so show it live rather than on completion. */}
          {group.handoff_input && (
            <SubagentTextBlock
              title="Task"
              content={group.handoff_input}
              className="mb-2"
            />
          )}
          <SubagentStepList
            steps={steps.visibleSteps}
            stepKeys={steps.stepKeys}
            lastIsTerminal
            callbacks={callbacks}
          />
        </div>
      )}
    </>
  );
}

function CompletedSubagentHeader({
  group,
  expanded,
  onToggle,
  toolCount,
}: Readonly<{
  group: EnrichedSubagentGroup;
  expanded: boolean;
  onToggle: () => void;
  toolCount: number;
}>) {
  return (
    <button
      type="button"
      className="min-h-8 flex flex-col justify-center w-full text-left group/sa cursor-pointer"
      onClick={onToggle}
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
        {toolCount > 0 && ` · ${toolCount} tool${toolCount === 1 ? "" : "s"}`}
      </p>
    </button>
  );
}

function CompletedSubagentBody({
  group,
  expanded,
  onToggle,
  steps,
  isStreaming,
  callbacks,
}: Readonly<SubagentBodyProps>) {
  const { visibleSteps } = steps;
  const hasNested = group.nested_subagents.length > 0;
  return (
    <>
      <CompletedSubagentHeader
        group={group}
        expanded={expanded}
        onToggle={onToggle}
        toolCount={steps.toolCount}
      />

      <AnimatePresence>
        {expanded && (
          <m.div
            layout
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={expandTransition}
            className="overflow-hidden"
          >
            <div className="mt-1.5 mb-1">
              {group.handoff_input && (
                <SubagentTextBlock
                  title="Task"
                  content={group.handoff_input}
                  className="mb-2"
                />
              )}

              <SubagentStepList
                steps={visibleSteps}
                stepKeys={steps.stepKeys}
                lastIsTerminal={!hasNested}
                callbacks={callbacks}
              />

              {hasNested && (
                <div className={visibleSteps.length > 0 ? "mt-1" : ""}>
                  {group.nested_subagents.map((nested) => (
                    <SubagentRow
                      key={`nested-${nested.subagent_id}`}
                      group={nested}
                      isLast
                      isStreaming={isStreaming}
                      {...callbacks}
                    />
                  ))}
                </div>
              )}

              {group.handoff_output && (
                <SubagentTextBlock
                  title="Result"
                  content={group.handoff_output}
                  className="mt-2"
                />
              )}
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </>
  );
}

export function SubagentRow({
  group,
  isLast,
  isStreaming,
  ...callbacks
}: Readonly<
  StepCallbacks & {
    group: EnrichedSubagentGroup;
    isLast: boolean;
    /** A subagent only counts as running while its stream is live, so a dropped `subagent_end` can't spin forever. */
    isStreaming: boolean;
  }
>) {
  // completed_at is null both while running AND when the end event never arrived; the live stream tells them apart.
  const isRunning = group.completed_at === null && isStreaming;
  // Start expanded while running so live tool calls are visible by default.
  const [expanded, setExpanded] = useState(() => isRunning);
  const bodyProps: SubagentBodyProps = {
    group,
    expanded,
    onToggle: () => setExpanded((e) => !e),
    steps: deriveSubagentSteps(group, callbacks.pendingApprovalToolCallIds),
    isStreaming,
    callbacks,
  };

  return (
    <div className="flex items-stretch gap-2 pb-2">
      <div className="flex flex-col items-center self-stretch">
        <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
          <SubagentIcon group={group} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-default-200 min-h-4" />}
      </div>
      <div className="flex-1 min-w-0">
        {isRunning ? (
          <RunningSubagentBody {...bodyProps} />
        ) : (
          <CompletedSubagentBody {...bodyProps} />
        )}
      </div>
    </div>
  );
}
