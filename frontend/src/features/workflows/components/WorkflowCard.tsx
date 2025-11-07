"use client";

import { useState } from "react";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

import { Workflow } from "../api/workflowApi";
import { getTriggerDisplay } from "../utils/triggerDisplay";
import BaseWorkflowCard from "./shared/BaseWorkflowCard";
import {
  ActivationStatus,
  getNextRunDisplay,
  RunWorkflowButton,
  TriggerDisplay,
} from "./shared/WorkflowCardComponents";

interface WorkflowCardProps {
  workflow: Workflow;
  onClick?: () => void;
  variant?: "management" | "execution";
  showArrowIcon?: boolean;
}

export default function WorkflowCard({
  workflow,
  onClick,
  variant = "management",
  showArrowIcon = true,
}: WorkflowCardProps) {
  const [isRunning, setIsRunning] = useState(false);
  const { selectWorkflow } = useWorkflowSelection();
  const { integrations } = useIntegrations();

  // Get trigger display info using integration data
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

  const getTriggerDisplayProps = () => {
    const nextRunText = getNextRunDisplay(workflow);
    return {
      triggerType: workflow.trigger_config.type,
      triggerLabel: triggerDisplay.label
        .split(" ")
        .map(
          (word: string) =>
            word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
        )
        .join(" "),
      integrationId: triggerDisplay.integrationId,
      nextRunText: nextRunText || undefined,
    };
  };

  const triggerProps = getTriggerDisplayProps();

  const footerContent =
    variant === "execution" ? (
      <RunWorkflowButton isLoading={isRunning} onPress={handleRunWorkflow} />
    ) : (
      <ActivationStatus activated={workflow.activated} />
    );

  return (
    <BaseWorkflowCard
      title={workflow.title}
      description={workflow.description}
      steps={workflow.steps}
      onClick={variant === "execution" ? handleRunWorkflow : onClick}
      showArrowIcon={showArrowIcon}
      triggerContent={<TriggerDisplay {...triggerProps} />}
      footerContent={footerContent}
      totalExecutions={workflow.total_executions}
    />
  );
}
