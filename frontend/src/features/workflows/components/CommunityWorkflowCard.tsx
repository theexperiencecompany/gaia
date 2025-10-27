"use client";

import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { useWorkflowSelection } from "@/features/chat/hooks/useWorkflowSelection";
import { useWorkflowCreation } from "@/features/workflows/hooks/useWorkflowCreation";

import { CommunityWorkflow } from "../api/workflowApi";
import BaseWorkflowCard from "./shared/BaseWorkflowCard";
import {
  CreateWorkflowButton,
  CreatorAvatar,
  TriggerDisplay,
} from "./shared/WorkflowCardComponents";

interface CommunityWorkflowCardProps {
  workflow: CommunityWorkflow;
  onClick?: () => void;
}

export default function CommunityWorkflowCard({
  workflow,
  onClick,
}: CommunityWorkflowCardProps) {
  const [isCreatingWorkflow, setIsCreatingWorkflow] = useState(false);
  const [localWorkflow, setLocalWorkflow] = useState(workflow);
  const debounceTimeoutRef = useRef<NodeJS.Timeout | null>(null);

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

  // const handleUpvoteImmediate = useCallback(async () => {
  //   if (isUpvoting) return;

  //   setIsUpvoting(true);

  //   // Store the current state for potential rollback
  //   const previousState = {
  //     is_upvoted: localWorkflow.is_upvoted,
  //     upvotes: localWorkflow.upvotes,
  //   };

  //   // Optimistic update - predict the action based on current state
  //   const predictedAction = localWorkflow.is_upvoted ? "removed" : "added";

  //   // Apply optimistic update immediately
  //   setLocalWorkflow((prev: CommunityWorkflow) => ({
  //     ...prev,
  //     is_upvoted: predictedAction === "added",
  //     upvotes:
  //       predictedAction === "added" ? prev.upvotes + 1 : prev.upvotes - 1,
  //   }));

  //   try {
  //     const result = await workflowApi.upvoteWorkflow(localWorkflow.id);

  //     // Verify optimistic update was correct, if not, apply correct state
  //     if (result.action !== predictedAction) {
  //       setLocalWorkflow((prev: CommunityWorkflow) => ({
  //         ...prev,
  //         is_upvoted: result.action === "added",
  //         upvotes:
  //           result.action === "added"
  //             ? previousState.upvotes + 1
  //             : previousState.upvotes - 1,
  //       }));
  //     }
  //   } catch (error) {
  //     console.error("Error upvoting workflow:", error);
  //     toast.error("Failed to update vote. Please try again.");

  //     // Rollback to previous state on error
  //     setLocalWorkflow((prev: CommunityWorkflow) => ({
  //       ...prev,
  //       is_upvoted: previousState.is_upvoted,
  //       upvotes: previousState.upvotes,
  //     }));
  //   } finally {
  //     setIsUpvoting(false);
  //   }
  // }, [
  //   isUpvoting,
  //   localWorkflow.is_upvoted,
  //   localWorkflow.upvotes,
  //   localWorkflow.id,
  // ]);

  // const handleUpvote = useCallback(() => {
  //   // Prevent rapid clicks by checking if already processing
  //   if (isUpvoting) return;

  //   // Clear any existing timeout
  //   if (debounceTimeoutRef.current) {
  //     clearTimeout(debounceTimeoutRef.current);
  //   }

  //   // Set new timeout for debouncing
  //   debounceTimeoutRef.current = setTimeout(() => {
  //     handleUpvoteImmediate();
  //   }, 300); // 300ms debounce
  // }, [isUpvoting, handleUpvoteImmediate]);

  // Cleanup timeout on unmount

  useEffect(() => {
    return () => {
      if (debounceTimeoutRef.current) {
        clearTimeout(debounceTimeoutRef.current);
      }
    };
  }, []);

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
    />
  );
}
