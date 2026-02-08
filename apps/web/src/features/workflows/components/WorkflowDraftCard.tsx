"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { useState } from "react";

import {
  Calendar03Icon,
  Clock01Icon,
  FlashIcon,
  FlowIcon,
  PencilEdit01Icon,
} from "@/icons";
import type { WorkflowDraftData } from "@/types/features/toolDataTypes";

import { getScheduleDescription } from "../utils/cronUtils";
import WorkflowModal from "./WorkflowModal";

interface WorkflowDraftCardProps {
  draft: WorkflowDraftData;
}

/**
 * Card component that displays a workflow draft preview from AI.
 * Renders its own modal inline - no global modal needed.
 * Styled to match the UnifiedWorkflowCard design patterns.
 */
export default function WorkflowDraftCard({ draft }: WorkflowDraftCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);

  const getTriggerDisplay = () => {
    switch (draft.trigger_type) {
      case "manual":
        return {
          label: "Manual",
          icon: <FlashIcon className="size-3.5" />,
          color: "default" as const,
          bgColor: "bg-zinc-700/50",
        };
      case "scheduled": {
        // Use human-readable format from cronUtils
        const cronLabel = draft.cron_expression
          ? getScheduleDescription(draft.cron_expression)
          : "Scheduled";
        return {
          label: cronLabel,
          icon: <Clock01Icon className="size-3.5" />,
          color: "primary" as const,
          bgColor: "bg-primary/15",
        };
      }
      case "integration":
        return {
          label:
            draft.trigger_slug
              ?.split("_")
              .slice(0, 2)
              .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
              .join(" ") || "Integration",
          icon: <Calendar03Icon className="size-3.5" />,
          color: "secondary" as const,
          bgColor: "bg-secondary/15",
        };
      default:
        return {
          label: "Unknown",
          icon: <FlashIcon className="size-3.5" />,
          color: "default" as const,
          bgColor: "bg-zinc-700/50",
        };
    }
  };

  const trigger = getTriggerDisplay();

  return (
    <>
      <div
        className="group relative z-1 flex w-full max-w-md cursor-pointer flex-col gap-3 rounded-3xl bg-zinc-800/40 p-4 outline-1 outline-zinc-800/50 backdrop-blur-lg transition-all hover:bg-zinc-700/50"
        onClick={() => setIsModalOpen(true)}
      >
        {/* Header with icon, title, and trigger badge */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-primary/15">
              <FlowIcon className="size-5 text-primary" />
            </div>
            <div className="flex flex-col">
              <span className="line-clamp-2 text-base font-medium leading-tight">
                {draft.suggested_title}
              </span>
              <span className="text-xs text-zinc-500">Workflow Draft</span>
            </div>
          </div>
          <Chip
            size="sm"
            variant="flat"
            color={trigger.color}
            startContent={trigger.icon}
            classNames={{
              base: `${trigger.bgColor} shrink-0`,
              content: "text-xs font-medium",
            }}
          >
            {trigger.label}
          </Chip>
        </div>

        {/* Description */}
        <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
          {draft.suggested_description}
        </p>

        {/* Action button */}
        <Button
          size="sm"
          color="primary"
          variant="flat"
          startContent={<PencilEdit01Icon className="size-3.5" />}
          onPress={() => setIsModalOpen(true)}
          className="mt-1 w-full rounded-xl font-medium"
        >
          Open in Editor
        </Button>
      </div>

      {/* Inline modal - no global modal needed */}
      {isModalOpen && (
        <WorkflowModal
          isOpen={isModalOpen}
          onOpenChange={setIsModalOpen}
          mode="create"
          draftData={draft}
        />
      )}
    </>
  );
}
