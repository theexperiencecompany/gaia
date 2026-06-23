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
                  "text-2xl font-semibold text-white placeholder:font-normal placeholder:text-zinc-600 focus:outline-none",
                inputWrapper:
                  "h-auto min-h-0 bg-transparent! px-0! py-0! shadow-none! outline-none! ring-0! border-0! data-[hover=true]:bg-transparent! data-[focus=true]:bg-transparent! data-[focus=true]:shadow-none! data-[focus-visible=true]:ring-0! data-[focus-visible=true]:outline-none! data-[focus-visible=true]:border-transparent!",
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

                {showPublish ? (
                  <DropdownItem
                    key="publish"
                    startContent={<GlobeIcon className="h-4 w-4" />}
                    classNames={{
                      description: "text-wrap",
                      base: "items-start!",
                    }}
                    description="Share to the community marketplace"
                  >
                    Publish
                  </DropdownItem>
                ) : null}

                {showMarketplace ? (
                  <DropdownItem
                    key="marketplace"
                    startContent={<LinkSquare02Icon className="h-4 w-4" />}
                    classNames={{
                      description: "text-wrap",
                      base: "items-start!",
                    }}
                    description="Open this workflow on the marketplace"
                  >
                    View on marketplace
                  </DropdownItem>
                ) : null}

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
                    Reset to default
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
              input: "resize-none text-sm text-zinc-300",
              inputWrapper:
                "bg-transparent! px-0! py-0! shadow-none! outline-none! ring-0! border-0! data-[hover=true]:bg-transparent! data-[focus=true]:bg-transparent! data-[focus=true]:shadow-none! data-[focus-visible=true]:ring-0! data-[focus-visible=true]:outline-none! data-[focus-visible=true]:border-transparent!",
            }}
            isInvalid={!!errors.description}
            errorMessage={errors.description?.message}
          />
        )}
      />
    </div>
  );
}
