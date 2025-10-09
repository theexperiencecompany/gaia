"use client";

import { Button } from "@heroui/button";
import { ArrowUpRight, Zap } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import BaseWorkflowCard from "@/features/workflows/components/shared/BaseWorkflowCard";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";
import { useAppendToInput } from "@/stores/composerStore";

interface UseCaseCardProps {
  title: string;
  description: string;
  action_type: "prompt" | "workflow";
  integrations: string[];
  prompt?: string;
}

export default function UseCaseCard({
  title,
  description,
  action_type,
  integrations,
  prompt,
}: UseCaseCardProps) {
  const [isCreatingWorkflow, setIsCreatingWorkflow] = useState(false);
  const appendToInput = useAppendToInput();
  const { selectWorkflow } = useWorkflowSelection();
  const { createWorkflow } = useWorkflowCreation();

  // Unified action handler for both card and button
  const handleAction = async () => {
    if (action_type === "prompt") {
      if (prompt) appendToInput(prompt);
    } else {
      setIsCreatingWorkflow(true);
      const toastId = toast.loading("Creating workflow...");
      try {
        const workflowRequest = {
          title,
          description,
          trigger_config: {
            type: "manual" as const,
            enabled: true,
          },
          generate_immediately: true,
        };
        const result = await createWorkflow(workflowRequest);
        if (result.success && result.workflow) {
          toast.success("Workflow created successfully!", { id: toastId });
          selectWorkflow(result.workflow, { autoSend: true });
        }
      } catch (error) {
        toast.error("Error creating workflow", { id: toastId });
        console.error("Workflow creation error:", error);
      } finally {
        setIsCreatingWorkflow(false);
      }
    }
  };

  const isLoading = action_type === "workflow" && isCreatingWorkflow;
  const footerContent = (
    <div className="mt-1 flex w-full flex-col justify-end gap-3">
      <Button
        color="primary"
        size="sm"
        variant="flat"
        className="ml-auto w-fit text-primary"
        endContent={
          (isLoading ? undefined : action_type === "prompt") && (
            <ArrowUpRight width={16} height={16} />
          )
        }
        isLoading={isLoading}
        onPress={handleAction}
      >
        {action_type === "prompt" ? "Insert Prompt" : "Create"}
      </Button>
    </div>
  );

  // Only make the card clickable if there is a single action and no modal
  const isCardClickable = true;

  return (
    <BaseWorkflowCard
      title={title}
      description={description}
      integrations={integrations}
      footerContent={footerContent}
      onClick={isCardClickable ? handleAction : undefined}
      showArrowIcon={false}
      useBlurEffect={true}
    />
  );
}
