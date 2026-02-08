import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input } from "@heroui/input";
import { useRouter } from "next/navigation";
import { type Control, Controller, type FieldErrors } from "react-hook-form";
import {
  Delete02Icon,
  LinkSquare02Icon,
  MoreVerticalIcon,
  PlayIcon,
} from "@/icons";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

import { type Workflow, workflowApi } from "../../api/workflowApi";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";

interface WorkflowHeaderProps {
  mode: "create" | "edit";
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  currentWorkflow: Workflow | null;
  onWorkflowChange: (workflow: Workflow | null) => void;
  onDelete: () => void;
  onRefetchWorkflows: () => void;
}

export default function WorkflowHeader({
  mode,
  control,
  errors,
  currentWorkflow,
  onWorkflowChange,
  onDelete,
  onRefetchWorkflows,
}: WorkflowHeaderProps) {
  const router = useRouter();

  const handlePublishToggle = async () => {
    if (!currentWorkflow?.id) return;

    try {
      if (currentWorkflow.is_public) {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_UNPUBLISHED, {
          workflow_id: currentWorkflow.id,
          workflow_title: currentWorkflow.title,
        });
        await workflowApi.unpublishWorkflow(currentWorkflow.id);
        onWorkflowChange(
          currentWorkflow ? { ...currentWorkflow, is_public: false } : null,
        );
      } else {
        trackEvent(ANALYTICS_EVENTS.WORKFLOWS_PUBLISHED, {
          workflow_id: currentWorkflow.id,
          workflow_title: currentWorkflow.title,
          step_count: currentWorkflow.steps?.length || 0,
        });
        await workflowApi.publishWorkflow(currentWorkflow.id);
        onWorkflowChange(
          currentWorkflow ? { ...currentWorkflow, is_public: true } : null,
        );
        if (currentWorkflow.id) {
          router.push(`/use-cases/${currentWorkflow.id}`);
        }
      }
      await onRefetchWorkflows();
    } catch (error) {
      console.error("Error publishing/unpublishing workflow:", error);
    }
  };

  const handleMarketplaceView = () => {
    if (currentWorkflow?.id) {
      router.push(`/use-cases/${currentWorkflow.id}`);
    }
  };

  return (
    <div className="flex items-center gap-3 pt-5">
      <Controller
        name="title"
        control={control}
        render={({ field }) => (
          <Input
            {...field}
            autoFocus
            placeholder={
              mode === "edit" ? "Edit workflow name" : "Enter workflow name"
            }
            variant="underlined"
            classNames={{
              input: "font-medium! text-4xl",
              inputWrapper: "px-0",
            }}
            isRequired
            className="flex-1"
            isInvalid={!!errors.title}
            errorMessage={errors.title?.message}
          />
        )}
      />

      {mode === "edit" && (
        <Dropdown placement="bottom-end" className="max-w-100">
          <DropdownTrigger>
            <Button variant="flat" size="sm" isIconOnly>
              <MoreVerticalIcon />
            </Button>
          </DropdownTrigger>
          <DropdownMenu
            onAction={async (key) => {
              if (key === "publish") {
                await handlePublishToggle();
              } else if (key === "marketplace") {
                handleMarketplaceView();
              } else if (key === "delete") {
                await onDelete();
              }
            }}
          >
            <DropdownItem
              key="publish"
              startContent={<PlayIcon className="relative top-1 h-4 w-4" />}
              classNames={{
                description: "text-wrap",
                base: "items-start!",
              }}
              description={
                currentWorkflow?.is_public
                  ? "Remove from community marketplace"
                  : "Share to community marketplace"
              }
            >
              {currentWorkflow?.is_public
                ? "Unpublish Workflow"
                : "Publish Workflow"}
            </DropdownItem>

            {currentWorkflow?.is_public ? (
              <DropdownItem
                key="marketplace"
                startContent={<LinkSquare02Icon className="h-4 w-4" />}
                classNames={{
                  description: "text-wrap",
                  base: "items-start!",
                }}
                description="Open community marketplace"
              >
                View on Marketplace
              </DropdownItem>
            ) : null}

            <DropdownItem
              key="delete"
              color="danger"
              startContent={<Delete02Icon className="h-4 w-4" />}
              classNames={{
                description: "text-wrap",
                base: "items-start!",
              }}
              description="Permanently delete this workflow"
            >
              Delete Workflow
            </DropdownItem>
          </DropdownMenu>
        </Dropdown>
      )}
    </div>
  );
}
