"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import {
  Calendar03Icon,
  CheckmarkCircle02Icon,
  Clock01Icon,
  FlashIcon,
  FlowIcon,
  PencilEdit01Icon,
} from "@icons";
import { useEffect, useState } from "react";
import type { WorkflowCreatedData } from "@/types/features/toolDataTypes";

import type { Workflow } from "../api/workflowApi";
import { workflowApi } from "../api/workflowApi";
import { getScheduleDescription } from "../utils/cronUtils";
import WorkflowModal from "./WorkflowModal";

interface WorkflowCreatedCardProps {
  workflow: WorkflowCreatedData;
}

/**
 * Card component that displays a successfully created workflow.
 * Shows the workflow with a success indicator and allows opening the edit modal.
 * Styled to match UnifiedWorkflowCard design patterns.
 */
export default function WorkflowCreatedCard({
  workflow,
}: WorkflowCreatedCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [fullWorkflow, setFullWorkflow] = useState<Workflow | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const getTriggerDisplay = () => {
    switch (workflow.trigger_config.type) {
      case "manual":
        return {
          label: "Manual",
          icon: <FlashIcon className="size-3.5" />,
          color: "default" as const,
          bgColor: "bg-zinc-700/50",
        };
      case "scheduled": {
        const cronLabel = workflow.trigger_config.cron_expression
          ? getScheduleDescription(workflow.trigger_config.cron_expression)
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
            workflow.trigger_config.trigger_name
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

  // Fetch full workflow when modal opens
  const handleOpenModal = async () => {
    setIsLoading(true);
    try {
      const response = await workflowApi.getWorkflow(workflow.id, {
        silent: true,
      });
      if (response?.workflow) {
        setFullWorkflow(response.workflow);
        // Only open modal if workflow was successfully fetched
        setIsModalOpen(true);
      }
    } catch (error) {
      console.error("Failed to fetch workflow:", error);
    } finally {
      setIsLoading(false);
    }
  };

  // Refresh workflow after modal closes (in case of edits)
  useEffect(() => {
    if (!isModalOpen && fullWorkflow) {
      // Refresh the workflow data
      workflowApi
        .getWorkflow(workflow.id, { silent: true })
        .then((response) => {
          if (response?.workflow) {
            setFullWorkflow(response.workflow);
          }
        })
        .catch((error) => {
          console.error("Failed to refresh workflow:", error);
        });
    }
  }, [isModalOpen, workflow.id]);

  return (
    <>
      <div className="group relative z-1 flex w-full max-w-md flex-col gap-3 rounded-3xl bg-zinc-800/40 p-4 outline-1 outline-zinc-800/50 backdrop-blur-lg transition-all">
        {/* Header with workflow icon and success indicator */}
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="flex size-10 shrink-0 items-center justify-center rounded-xl bg-success/15">
              <FlowIcon className="size-5 text-success" />
            </div>
            <div className="flex flex-col">
              <span className="line-clamp-2 text-base font-medium leading-tight">
                {workflow.title}
              </span>
              <span className="text-xs text-zinc-500">Workflow Created</span>
            </div>
          </div>
          <Chip
            size="sm"
            variant="flat"
            color="success"
            startContent={<CheckmarkCircle02Icon className="size-3" />}
            classNames={{
              base: "bg-success/15 shrink-0",
              content: "text-xs font-medium",
            }}
          >
            Created
          </Chip>
        </div>

        {/* Description */}
        <p className="line-clamp-2 text-xs leading-relaxed text-zinc-400">
          {workflow.description}
        </p>

        {/* Trigger display */}
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

        {/* Action button */}
        <Button
          size="sm"
          color="primary"
          variant="flat"
          startContent={<PencilEdit01Icon className="size-3.5" />}
          isLoading={isLoading}
          onPress={handleOpenModal}
          className="mt-1 w-full rounded-xl font-medium"
        >
          View & Edit
        </Button>
      </div>

      {/* Edit modal - only render when we have the full workflow */}
      {isModalOpen && (
        <WorkflowModal
          isOpen={isModalOpen}
          onOpenChange={setIsModalOpen}
          mode="edit"
          existingWorkflow={fullWorkflow}
        />
      )}
    </>
  );
}
