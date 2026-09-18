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
    <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-amber-400">
      <ShieldAlertIcon width={13} height={13} />
      Waiting for approval
    </span>
  );
}

// A settled decision rides its tool's own row — one place tells the whole story.
const APPROVAL_CHIP: Record<
  string,
  { label: string; color: "success" | "danger" | "warning" }
> = {
  approved: { label: "Approved", color: "success" },
  auto_approved: { label: "Auto-approved", color: "success" },
  denied: { label: "Denied", color: "danger" },
  timeout: { label: "Expired", color: "warning" },
  abandoned: { label: "Expired", color: "warning" },
};

function ApprovalOutcomeChip({ status }: Readonly<{ status: ApprovalStatus }>) {
  const chip = APPROVAL_CHIP[status];
  if (!chip) return null;
  return (
    <Chip
      size="sm"
      variant="flat"
      color={chip.color}
      className="ml-2 h-5 text-xs"
    >
      {chip.label}
    </Chip>
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
        <div className="absolute inset-0 rounded-lg bg-lime-400/20 backdrop-blur" />
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
  approvalStatus,
}: Readonly<{
  display: ToolCallDisplay;
  expanded: boolean;
  onToggle: () => void;
  awaitingApproval: boolean;
  approvalStatus?: ApprovalStatus;
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
        {approvalStatus && <ApprovalOutcomeChip status={approvalStatus} />}
      </div>
      {hasCategoryText && (
        <p className="text-xs text-zinc-600 leading-tight">
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
          <div className="mt-2 space-y-2 bg-zinc-800/50 rounded-xl p-3 mb-3 w-fit text-xs">
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
  approvalStatus,
}: Readonly<{
  call: ToolCallEntry;
  isLast: boolean;
  getIconUrl: (c: ToolCallEntry) => string | undefined;
  getIntegrationName: (c: ToolCallEntry) => string | undefined;
  awaitingApproval: boolean;
  approvalStatus?: ApprovalStatus;
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
          approvalStatus={approvalStatus}
        />
        <ToolCallDetails call={call} display={display} expanded={expanded} />
      </div>
    </div>
  );
}
