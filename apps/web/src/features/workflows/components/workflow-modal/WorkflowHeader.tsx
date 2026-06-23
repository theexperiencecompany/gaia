import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
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
  GlobeIcon,
  LinkSquare02Icon,
  MoreVerticalIcon,
  ReloadIcon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@icons";
import { type Control, Controller, type FieldErrors } from "react-hook-form";

import { cn } from "@/lib/utils";
import type { Workflow } from "../../api/workflowApi";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";

const iconClasses = "size-5 text-default-500 pointer-events-none shrink-0";

interface WorkflowHeaderProps {
  mode: "create" | "edit" | "preview";
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  currentWorkflow: Workflow | null;
  isActivated: boolean;
  isTogglingActivation: boolean;
  onToggleActivation: (activated: boolean) => void;
  isPublic?: boolean;
  onPublish?: () => void | Promise<void>;
  onUnpublish?: () => void | Promise<void>;
  onViewMarketplace?: () => void;
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
  onPublish,
  onUnpublish,
  onViewMarketplace,
  onDelete,
  onResetToDefault,
}: WorkflowHeaderProps) {
  const isSystemWorkflow = !!currentWorkflow?.is_system_workflow;
  const showPublish = !isPublic && !!onPublish;
  const showMarketplace = !!isPublic && !!onViewMarketplace;
  const showUnpublish = !!isPublic && !!onUnpublish;
  const showReset = isSystemWorkflow && !!onResetToDefault;
  const showMenu = mode === "edit" && !!currentWorkflow;

  return (
    <div className="space-y-1">
      <div className="flex items-start gap-3">
        <Controller
          name="title"
          control={control}
          render={({ field }) => (
            <Input
              {...field}
              autoFocus
              placeholder={
                mode === "edit" ? "Workflow name" : "Name your workflow"
              }
              variant="flat"
              classNames={{
                base: "min-w-0 flex-1",
                input:
                  "text-2xl font-semibold text-white placeholder:font-normal placeholder:text-zinc-600 focus:outline-none focus-visible:outline-none",
                inputWrapper:
                  "h-auto min-h-0 border-none bg-transparent px-0 py-0 shadow-none outline-none ring-0 data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent group-data-[focus=true]:shadow-none group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0",
              }}
              isRequired
              isInvalid={!!errors.title}
              errorMessage={errors.title?.message}
            />
          )}
        />

        {showMenu && (
          <div className="flex shrink-0 items-center gap-2 pt-1.5">
            <Chip
              size="sm"
              variant="flat"
              color={isActivated ? "success" : "default"}
              classNames={{
                base: isActivated ? "bg-success/15" : "bg-zinc-800",
                content: "text-xs font-medium",
              }}
            >
              {isActivated ? "Active" : "Paused"}
            </Chip>

            <Dropdown placement="bottom-end" className="w-64">
              <DropdownTrigger>
                <Button variant="flat" size="sm" isIconOnly>
                  <MoreVerticalIcon className="h-4 w-4" />
                </Button>
              </DropdownTrigger>
              <DropdownMenu
                variant="faded"
                disabledKeys={isTogglingActivation ? ["activation"] : []}
                onAction={(key) => {
                  if (key === "activation") onToggleActivation(!isActivated);
                  else if (key === "publish") onPublish?.();
                  else if (key === "marketplace") onViewMarketplace?.();
                  else if (key === "unpublish") onUnpublish?.();
                  else if (key === "reset") onResetToDefault?.();
                  else if (key === "delete") onDelete();
                }}
              >
                <DropdownItem
                  key="activation"
                  description={
                    isActivated
                      ? "Stop this workflow from running"
                      : "Allow this workflow to run"
                  }
                  startContent={
                    isActivated ? (
                      <ToggleOffIcon className={iconClasses} />
                    ) : (
                      <ToggleOnIcon className={iconClasses} />
                    )
                  }
                >
                  {isActivated ? "Disable" : "Enable"}
                </DropdownItem>

                {showPublish ? (
                  <DropdownItem
                    key="publish"
                    description="Share to the marketplace"
                    startContent={<GlobeIcon className={iconClasses} />}
                  >
                    Publish
                  </DropdownItem>
                ) : null}

                {showMarketplace ? (
                  <DropdownItem
                    key="marketplace"
                    description="Open on the marketplace"
                    startContent={<LinkSquare02Icon className={iconClasses} />}
                  >
                    View on marketplace
                  </DropdownItem>
                ) : null}

                {showUnpublish ? (
                  <DropdownItem
                    key="unpublish"
                    description="Remove from the marketplace"
                    startContent={<Cancel01Icon className={iconClasses} />}
                  >
                    Unpublish
                  </DropdownItem>
                ) : null}

                {showReset ? (
                  <DropdownItem
                    key="reset"
                    description="Restore the original GAIA definition"
                    startContent={<ReloadIcon className={iconClasses} />}
                  >
                    Reset to default
                  </DropdownItem>
                ) : null}

                <DropdownItem
                  key="delete"
                  className="text-danger"
                  color="danger"
                  description="Permanently delete this workflow"
                  startContent={
                    <Delete02Icon className={cn(iconClasses, "text-danger")} />
                  }
                >
                  Delete workflow
                </DropdownItem>
              </DropdownMenu>
            </Dropdown>
          </div>
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
            maxRows={2}
            variant="flat"
            classNames={{
              input:
                "resize-none text-sm text-zinc-300 focus:outline-none focus-visible:outline-none",
              inputWrapper:
                "border-none bg-transparent px-0 py-0 shadow-none outline-none ring-0 data-[hover=true]:bg-transparent group-data-[focus=true]:bg-transparent group-data-[focus=true]:shadow-none group-data-[focus-visible=true]:ring-0 group-data-[focus-visible=true]:ring-offset-0",
            }}
            isInvalid={!!errors.description}
            errorMessage={errors.description?.message}
          />
        )}
      />
    </div>
  );
}
