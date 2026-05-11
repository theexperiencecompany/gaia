import { Button } from "@heroui/button";
import {
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownTrigger,
} from "@heroui/dropdown";
import { Input, Textarea } from "@heroui/input";
import {
  Cancel01Icon,
  Delete02Icon,
  MoreVerticalIcon,
  ReloadIcon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@icons";
import { type Control, Controller, type FieldErrors } from "react-hook-form";

import type { Workflow } from "../../api/workflowApi";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";

interface WorkflowHeaderProps {
  mode: "create" | "edit" | "preview";
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  currentWorkflow: Workflow | null;
  isActivated: boolean;
  isTogglingActivation: boolean;
  onToggleActivation: (activated: boolean) => void;
  isPublic?: boolean;
  onUnpublish?: () => void | Promise<void>;
  onDelete: () => void;
  onResetToDefault?: () => void | Promise<void>;
}

export default function WorkflowHeader({
  mode,
  control,
  errors,
  currentWorkflow,
  isActivated,
  isTogglingActivation,
  onToggleActivation,
  isPublic,
  onUnpublish,
  onDelete,
  onResetToDefault,
}: WorkflowHeaderProps) {
  const isSystemWorkflow = !!currentWorkflow?.is_system_workflow;
  const showUnpublish = !!isPublic && !!onUnpublish;
  const showReset = isSystemWorkflow && !!onResetToDefault;

  return (
    <div className="flex flex-col pt-5">
      <div className="flex items-center gap-3">
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

        {mode === "edit" && currentWorkflow && (
          <Dropdown placement="bottom-end" className="w-64">
            <DropdownTrigger>
              <Button variant="flat" size="sm" isIconOnly>
                <MoreVerticalIcon />
              </Button>
            </DropdownTrigger>
            <DropdownMenu
              disabledKeys={isTogglingActivation ? ["activation"] : []}
              onAction={(key) => {
                if (key === "activation") {
                  onToggleActivation(!isActivated);
                } else if (key === "unpublish" && onUnpublish) {
                  onUnpublish();
                } else if (key === "reset" && onResetToDefault) {
                  onResetToDefault();
                } else if (key === "delete") {
                  onDelete();
                }
              }}
            >
              <DropdownItem
                key="activation"
                startContent={
                  isActivated ? (
                    <ToggleOffIcon className="h-4 w-4" />
                  ) : (
                    <ToggleOnIcon className="h-4 w-4" />
                  )
                }
                classNames={{
                  description: "text-wrap",
                  base: "items-start!",
                }}
                description={
                  isActivated
                    ? "Stop this workflow from running"
                    : "Allow this workflow to run"
                }
              >
                {isActivated ? "Disable" : "Enable"}
              </DropdownItem>

              {showUnpublish ? (
                <DropdownItem
                  key="unpublish"
                  startContent={<Cancel01Icon className="h-4 w-4" />}
                  classNames={{
                    description: "text-wrap",
                    base: "items-start!",
                  }}
                  description="Remove from community marketplace"
                >
                  Unpublish
                </DropdownItem>
              ) : null}

              {showReset ? (
                <DropdownItem
                  key="reset"
                  startContent={<ReloadIcon className="h-4 w-4" />}
                  classNames={{
                    description: "text-wrap",
                    base: "items-start!",
                  }}
                  description="Restore this workflow to its original GAIA-provided definition"
                >
                  Reset to Default
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

      <Controller
        name="description"
        control={control}
        render={({ field }) => (
          <Textarea
            {...field}
            value={field.value ?? ""}
            placeholder="Add a short description..."
            minRows={1}
            maxRows={3}
            variant="underlined"
            classNames={{
              input: "text-sm text-foreground-500 resize-none",
              inputWrapper: "px-0",
            }}
            isInvalid={!!errors.description}
            errorMessage={errors.description?.message}
          />
        )}
      />
    </div>
  );
}
