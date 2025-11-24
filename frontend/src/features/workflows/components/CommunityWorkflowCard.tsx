"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";

import type { CommunityWorkflow } from "../api/workflowApi";
import BaseWorkflowCard from "./shared/BaseWorkflowCard";
import {
  CreateWorkflowButton,
  CreatorAvatar,
  TriggerDisplay,
} from "./shared/WorkflowCardComponents";

interface CommunityWorkflowCardProps {
  workflow: CommunityWorkflow;
  onClick?: () => void;
  useBlurEffect?: boolean;
}

export default function CommunityWorkflowCard({
  workflow,
  onClick,
  useBlurEffect = false,
}: CommunityWorkflowCardProps) {
  const [isCreatingWorkflow, setIsCreatingWorkflow] = useState(false);
  const [localWorkflow, setLocalWorkflow] = useState(workflow);

  const { selectWorkflow } = useWorkflowSelection();
  const { createWorkflow } = useWorkflowCreation();

  // Sync local state when workflow prop changes
  useEffect(() => {
    setLocalWorkflow(workflow);
  }, [workflow]);

  const handleCreateWorkflow = async () => {
    setIsCreatingWorkflow(true);
    const toastId = toast.loading("Creating workflow...");

    try {
      const workflowRequest = {
        title: localWorkflow.title,
        description: localWorkflow.description,
        trigger_config: {
          type: "manual" as const,
          enabled: true,
        },
        generate_immediately: true,
      };

      const result = await createWorkflow(workflowRequest);

      if (result.success && result.workflow) {
        toast.success("Workflow created successfully!", { id: toastId });
        // Use selectWorkflow with autoSend option - this handles both navigation and auto-send flag
        selectWorkflow(result.workflow, { autoSend: false });
      }
    } catch (error) {
      toast.error("Error creating workflow", { id: toastId });
      console.error("Workflow creation error:", error);
    } finally {
      setIsCreatingWorkflow(false);
    }
  };

  const triggerContent = (
    <TriggerDisplay triggerType="manual" triggerLabel="Manual" />
  );

  const footerContent = (
    <div className="flex items-center gap-3">
      {localWorkflow.creator && (
        <CreatorAvatar creator={localWorkflow.creator} />
      )}
      <CreateWorkflowButton
        isLoading={isCreatingWorkflow}
        onPress={handleCreateWorkflow}
      />
    </div>
  );

  return (
    <BaseWorkflowCard
      title={localWorkflow.title}
      description={localWorkflow.description}
      steps={localWorkflow.steps}
      triggerContent={triggerContent}
      footerContent={footerContent}
      totalExecutions={0}
      onClick={onClick}
      useBlurEffect={useBlurEffect}
      showArrowIcon={!!onClick}
    />
  );
}
