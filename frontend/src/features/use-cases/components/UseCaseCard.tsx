"use client";

import { Button } from "@heroui/button";
import { ArrowUpRight } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import { posthog } from "@/lib";

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
  slug?: string;
}

export default function UseCaseCard({
  title,
  description,
  action_type,
  integrations,
  prompt,
  slug,
}: UseCaseCardProps) {
  const router = useRouter();
  const [isCreatingWorkflow, setIsCreatingWorkflow] = useState(false);
  const appendToInput = useAppendToInput();
  const { selectWorkflow } = useWorkflowSelection();
  const { createWorkflow } = useWorkflowCreation();

  // Handler for card click - navigate to detail page
  const handleCardClick = () => {
    if (slug) {
      posthog.capture("use_cases:card_clicked", {
        title,
        slug,
        action_type,
        integrations,
      });
      router.push(`/use-cases/${slug}`);
    }
  };

  // Action handler for the action button
  const handleAction = async () => {
    posthog.capture("use_cases:action_executed", {
      title,
      action_type,
      integrations,
      has_prompt: !!prompt,
    });

    if (action_type === "prompt") {
      if (prompt) {
        appendToInput(prompt);
        router.push("/c");
      }
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
    <div className="mt-1 flex w-full items-center justify-end gap-3">
      <Button
        color="primary"
        size="sm"
        variant="flat"
        className="w-fit text-primary"
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

  return (
    <BaseWorkflowCard
      title={title}
      description={description}
      integrations={integrations}
      footerContent={footerContent}
      onClick={slug ? handleCardClick : undefined}
      showArrowIcon={false}
    />
  );
}
