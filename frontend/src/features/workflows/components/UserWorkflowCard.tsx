"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { useState } from "react";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Workflow } from "@/features/workflows/api/workflowApi";

import { getTriggerDisplay } from "../utils/triggerDisplay";
import BaseWorkflowCard from "./shared/BaseWorkflowCard";
import { TriggerIcon } from "./shared/WorkflowCardComponents";

interface UserWorkflowCardProps {
  workflow: Workflow;
}

export default function UserWorkflowCard({ workflow }: UserWorkflowCardProps) {
  const [isRunning, setIsRunning] = useState(false);
  const { selectWorkflow } = useWorkflowSelection();
  const { integrations } = useIntegrations();

  const triggerDisplay = getTriggerDisplay(workflow, integrations);

  const handleRunWorkflow = async () => {
    if (isRunning) return;
    setIsRunning(true);
    try {
      selectWorkflow(workflow, { autoSend: true });
    } catch (error) {
      console.error("Error running workflow:", error);
    } finally {
      setIsRunning(false);
    }
  };

  const footerContent = (
    <div className="flex w-full flex-col gap-3">
      {/* Trigger information */}
      <div className="flex items-center gap-2">
        <Chip
          size="sm"
          startContent={
            <TriggerIcon
              triggerType={workflow.trigger_config.type}
              integrationId={triggerDisplay.integrationId}
              size={15}
            />
          }
          radius="sm"
          variant="light"
          className="flex gap-1 px-2! text-zinc-400"
        >
          {triggerDisplay.label
            .split(" ")
            .map(
              (word) =>
                word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
            )
            .join(" ")}
        </Chip>
      </div>

      <Button
        color="primary"
        size="sm"
        isLoading={isRunning}
        onPress={handleRunWorkflow}
        variant="flat"
        className="ml-auto w-fit text-primary"
      >
        Run Workflow
      </Button>
    </div>
  );

  return (
    <BaseWorkflowCard
      title={workflow.title}
      description={workflow.description}
      steps={workflow.steps}
      footerContent={footerContent}
      onClick={handleRunWorkflow}
      showArrowIcon={false}
      totalExecutions={workflow.total_executions}
    />
  );
}
