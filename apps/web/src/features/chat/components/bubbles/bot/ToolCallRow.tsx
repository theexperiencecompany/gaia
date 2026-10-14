"use client";

import { Chip } from "@heroui/chip";
import { PuzzleIcon, ToolsIcon } from "@icons";
import type { ApprovalStatus } from "@shared/chat";
import { AnimatePresence } from "motion/react";
import * as m from "motion/react-m";
import { useState } from "react";
import { ChevronDown, ShieldAlertIcon } from "@/components/shared/icons";
import { CompactMarkdown } from "@/components/ui/CompactMarkdown";
import type { ToolCallEntry } from "@/config/registries/toolRegistry";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import {
  deriveToolCallDisplay,
  displayToolOutput,
  expandTransition,
  type ToolCallDisplay,
} from "./toolCallDisplay";

// Shown in place of the running spinner so the tree explains why a step is stuck on HIL approval.
export function WaitingForApprovalPill() {
  return (
    <span className="flex shrink-0 items-center gap-1 text-[11px] font-medium text-amber-400">
      <ShieldAlertIcon width={13} height={13} />
      Waiting for approval
    </span>
  );
}

// A settled decision rides its tool's own row — one place tells the whole story.
// The receipt (execution outcome, denial reason) travels as feedback so the row
// shows not just "Approved" but what the approval did.
export interface ApprovalOutcome {
  status: ApprovalStatus;
  feedback: string | null;
}

const APPROVAL_CHIP: Record<
  string,
  { label: string; color: "success" | "danger" | "warning" }
> = {
  approved: { label: "Approved", color: "success" },
  auto_approved: { label: "Auto-approved", color: "success" },
  denied: { label: "Denied", color: "danger" },
  revoked: { label: "Withdrawn", color: "warning" },
  timeout: { label: "Expired", color: "warning" },
  abandoned: { label: "Expired", color: "warning" },
  executed: { label: "Executed", color: "success" },
  failed: { label: "Failed", color: "danger" },
  unknown: { label: "Unknown", color: "warning" },
};

function ApprovalOutcomeChip({
  outcome,
}: Readonly<{ outcome: ApprovalOutcome }>) {
  const chip = APPROVAL_CHIP[outcome.status];
  if (!chip) return null;
  return (
    <span className="ml-2 inline-flex min-w-0 items-center gap-1.5">
      <Chip
        size="sm"
        variant="flat"
        color={chip.color}
        className="h-5 shrink-0 text-[10px]"
      >
        {chip.label}
      </Chip>
      {outcome.feedback && (
        <span className="truncate text-[10px] text-zinc-500">
          {outcome.feedback}
        </span>
      )}
    </span>
  );
}

function ToolCallIcon({
  call,
  isSkill,
  getIconUrl,
}: Readonly<{
  call: ToolCallEntry;
  isSkill: boolean;
  getIconUrl: (c: ToolCallEntry) => string | undefined;
}>) {
  if (isSkill) {
    return (
      <div className="relative rounded-lg p-1">
        <div className="absolute inset-0 rounded-lg bg-lime-500/20 backdrop-blur" />
        <PuzzleIcon width={21} height={21} className="relative text-lime-400" />
      </div>
    );
  }
  return (
    getToolCategoryIcon(
      call.tool_category || "general",
      { size: 21, width: 21, height: 21 },
      getIconUrl(call),
    ) || (
      <div className="p-1 bg-zinc-800 rounded-lg">
        <ToolsIcon width={21} height={21} />
      </div>
    )
  );
}

function ToolCallHeader({
  display,
  expanded,
  onToggle,
  awaitingApproval,
  approvalOutcome,
}: Readonly<{
  display: ToolCallDisplay;
  expanded: boolean;
  onToggle: () => void;
  awaitingApproval: boolean;
  approvalOutcome?: ApprovalOutcome;
}>) {
  const { hasCategoryText, hasDetails } = display;
  return (
    <button
      type="button"
      className={`w-full text-left group/parent ${hasCategoryText ? "min-h-8 flex flex-col justify-center" : "flex items-center min-h-8"} ${hasDetails ? "cursor-pointer" : "cursor-default"}`}
      onClick={() => hasDetails && onToggle()}
    >
      <div className="flex items-center gap-1">
        <p
          className={`text-xs text-zinc-400 font-medium ${hasDetails ? "group-hover/parent:text-white transition-colors" : ""}`}
        >
          {display.primaryLabel}
        </p>
        {hasDetails && (
          <ChevronDown
            className={`text-zinc-500 transition-transform duration-200 ${expanded ? "rotate-180" : ""}`}
            width={14}
            height={14}
          />
        )}
        {awaitingApproval && (
          <span className="ml-2">
            <WaitingForApprovalPill />
          </span>
        )}
        {approvalOutcome && <ApprovalOutcomeChip outcome={approvalOutcome} />}
      </div>
      {hasCategoryText && (
        <p className="text-[11px] text-zinc-600 leading-tight">
          {display.secondaryLabel}
        </p>
      )}
    </button>
  );
}

function ToolCallDetails({
  call,
  display,
  expanded,
}: Readonly<{
  call: ToolCallEntry;
  display: ToolCallDisplay;
  expanded: boolean;
}>) {
  return (
    <AnimatePresence>
      {expanded && display.hasDetails && (
        <m.div
          layout
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={expandTransition}
          className="overflow-hidden"
        >
          <div className="mt-2 space-y-2 text-[11px] bg-zinc-800/50 rounded-xl p-3 mb-3 w-fit">
            {display.hasInputs && (
              <div className="flex flex-col">
                <span className="text-zinc-500 font-medium mb-1">Input</span>
                <CompactMarkdown content={call.inputs} />
              </div>
            )}
            {display.hasOutput && (
              <div className="flex flex-col">
                <span className="text-zinc-500 font-medium mb-1">Output</span>
                <CompactMarkdown content={displayToolOutput(call)} />
              </div>
            )}
          </div>
        </m.div>
      )}
    </AnimatePresence>
  );
}

export function ToolCallRow({
  call,
  isLast,
  getIconUrl,
  getIntegrationName,
  awaitingApproval,
  approvalOutcome,
}: Readonly<{
  call: ToolCallEntry;
  isLast: boolean;
  getIconUrl: (c: ToolCallEntry) => string | undefined;
  getIntegrationName: (c: ToolCallEntry) => string | undefined;
  awaitingApproval: boolean;
  approvalOutcome?: ApprovalOutcome;
}>) {
  const [expanded, setExpanded] = useState(false);
  const display = deriveToolCallDisplay(call, getIntegrationName);

  return (
    <div className="flex items-stretch gap-2">
      <div className="flex flex-col items-center self-stretch">
        <div className="min-h-8 min-w-8 flex items-center justify-center shrink-0">
          <ToolCallIcon
            call={call}
            isSkill={!!display.skillLabel}
            getIconUrl={getIconUrl}
          />
        </div>
        {!isLast && <div className="w-px flex-1 bg-default-200 min-h-4" />}
      </div>

      <div className="flex-1 min-w-0">
        <ToolCallHeader
          display={display}
          expanded={expanded}
          onToggle={() => setExpanded(!expanded)}
          awaitingApproval={awaitingApproval}
          approvalOutcome={approvalOutcome}
        />
        <ToolCallDetails call={call} display={display} expanded={expanded} />
      </div>
    </div>
  );
}
