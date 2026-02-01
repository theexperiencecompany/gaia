"use client";

import { Button } from "@heroui/button";
import { Card, CardBody, CardHeader } from "@heroui/card";
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

import WorkflowModal from "./WorkflowModal";

interface WorkflowDraftCardProps {
  draft: WorkflowDraftData;
}

/**
 * Card component that displays a workflow draft preview from AI.
 * Renders its own modal inline - no global modal needed.
 */
export default function WorkflowDraftCard({ draft }: WorkflowDraftCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);

  const getTriggerDisplay = () => {
    switch (draft.trigger_type) {
      case "manual":
        return {
          label: "Manual",
          icon: <FlashIcon className="size-3" />,
          color: "default" as const,
        };
      case "scheduled":
        return {
          label: draft.cron_expression || "Scheduled",
          icon: <Clock01Icon className="size-3" />,
          color: "primary" as const,
        };
      case "integration":
        return {
          label:
            draft.trigger_slug?.split("_").slice(0, 2).join(" ") ||
            "Integration",
          icon: <Calendar03Icon className="size-3" />,
          color: "secondary" as const,
        };
      default:
        return {
          label: "Unknown",
          icon: <FlashIcon className="size-3" />,
          color: "default" as const,
        };
    }
  };

  const trigger = getTriggerDisplay();

  return (
    <>
      <Card className="w-full max-w-md border border-default-200 bg-default-50">
        <CardHeader className="flex items-center gap-2 pb-2">
          <div className="flex size-8 items-center justify-center rounded-lg bg-primary/10">
            <FlowIcon className="size-4 text-primary" />
          </div>
          <div className="flex flex-1 flex-col">
            <span className="text-sm font-medium">{draft.suggested_title}</span>
            <span className="text-xs text-default-500">Workflow Draft</span>
          </div>
          <Chip
            size="sm"
            variant="flat"
            color={trigger.color}
            startContent={trigger.icon}
          >
            {trigger.label}
          </Chip>
        </CardHeader>
        <CardBody className="pt-0">
          <p className="mb-3 text-xs text-default-600">
            {draft.suggested_description}
          </p>

          {draft.steps && draft.steps.length > 0 && (
            <div className="mb-3">
              <span className="mb-1 block text-xs font-medium text-default-500">
                Steps ({draft.steps.length})
              </span>
              <div className="space-y-1">
                {draft.steps.slice(0, 3).map((step, index) => (
                  <div
                    key={`step-${step.substring(0, 20)}-${index}`}
                    className="flex items-center gap-2 text-xs text-default-600"
                  >
                    <span className="flex size-4 shrink-0 items-center justify-center rounded-full bg-default-200 text-[10px] font-medium">
                      {index + 1}
                    </span>
                    <span className="truncate">{step}</span>
                  </div>
                ))}
                {draft.steps.length > 3 && (
                  <span className="text-[10px] text-default-400">
                    +{draft.steps.length - 3} more steps
                  </span>
                )}
              </div>
            </div>
          )}

          <Button
            size="sm"
            color="primary"
            variant="flat"
            startContent={<PencilEdit01Icon className="size-3" />}
            onPress={() => setIsModalOpen(true)}
            className="w-full"
          >
            Open in Editor
          </Button>
        </CardBody>
      </Card>

      {/* Inline modal - no global modal needed */}
      <WorkflowModal
        isOpen={isModalOpen}
        onOpenChange={setIsModalOpen}
        mode="create"
        draftData={draft}
      />
    </>
  );
}
