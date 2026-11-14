import {
  Chip,
  Description,
  Dropdown,
  DropdownItem,
  DropdownMenu,
  DropdownPopover,
  DropdownTrigger,
  FieldError,
  Input,
  Label,
  TextArea,
  TextField,
} from "@heroui/react";
import {
  Cancel01Icon,
  Delete02Icon,
  LinkSquare02Icon,
  MoreVerticalIcon,
  ReloadIcon,
  ToggleOffIcon,
  ToggleOnIcon,
} from "@icons";
import { type Control, Controller, type FieldErrors } from "react-hook-form";
import {
  chipVariants,
  inputVariants,
} from "@/components/shared/controlVariants";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { toneVariants } from "@/components/shared/tone";
import { cn } from "@/lib/utils";
import type { Workflow } from "../../api/workflowApi";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";
import { NeedsSetupChip } from "../shared/WorkflowCardComponents";
import WorkflowIconPicker from "./WorkflowIconPicker";

const iconClasses = "size-5 text-zinc-400 pointer-events-none shrink-0";

interface WorkflowHeaderProps {
  mode: "create" | "edit" | "preview";
  control: Control<WorkflowFormData>;
  errors: FieldErrors<WorkflowFormData>;
  currentWorkflow: Workflow | null;
  isActivated: boolean;
  /** Integrations are missing, so the workflow cannot run whatever its stored
   *  activation says — the status chip must not claim otherwise. */
  needsSetup?: boolean;
  isTogglingActivation: boolean;
  onToggleActivation: (activated: boolean) => void;
  isPublic?: boolean;
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
  needsSetup = false,
  isTogglingActivation,
  onToggleActivation,
  isPublic,
  onUnpublish,
  onViewMarketplace,
  onDelete,
  onResetToDefault,
}: WorkflowHeaderProps) {
  const isSystemWorkflow = !!currentWorkflow?.is_system_workflow;
  const showMarketplace = !!isPublic && !!onViewMarketplace;
  const showUnpublish = !!isPublic && !!onUnpublish;
  const showReset = isSystemWorkflow && !!onResetToDefault;
  const showMenu = mode === "edit" && !!currentWorkflow;

  return (
    <div className="space-y-1">
      <div className="flex items-start gap-3">
        <WorkflowIconPicker control={control} isReadOnly={mode === "preview"} />
        <Controller
          name="title"
          control={control}
          render={({ field }) => (
            <TextField
              className="min-w-0 flex-1"
              name={field.name}
              value={field.value ?? ""}
              onChange={field.onChange}
              onBlur={field.onBlur}
              isRequired
              isInvalid={!!errors.title}
            >
              <Input
                ref={field.ref}
                autoFocus
                placeholder={
                  mode === "edit" ? "Workflow name" : "Name your workflow"
                }
                className={inputVariants({
                  variant: "bare",
                  placeholder: "subtle",
                  className: toneVariants({
                    tone: "white",
                    className: "h-auto min-h-0 text-2xl font-semibold",
                  }),
                })}
              />
              <FieldError>{errors.title?.message}</FieldError>
            </TextField>
          )}
        />

        {showMenu && (
          <div className="flex shrink-0 items-center gap-2 pt-1.5">
            {needsSetup ? (
              <NeedsSetupChip />
            ) : (
              <Chip
                size="sm"
                variant={isActivated ? "soft" : "secondary"}
                color={isActivated ? "success" : "default"}
                className={chipVariants({
                  tint: isActivated ? "light" : "default",
                })}
              >
                <Chip.Label className="text-xs font-medium">
                  {isActivated ? "Active" : "Paused"}
                </Chip.Label>
              </Chip>
            )}

            <Dropdown>
              <DropdownTrigger>
                <GaiaButton
                  aria-label="More options"
                  variant="default-soft"
                  size="sm"
                  isIconOnly
                >
                  <MoreVerticalIcon className="h-4 w-4" />
                </GaiaButton>
              </DropdownTrigger>
              <DropdownPopover placement="bottom end" className="w-64">
                <DropdownMenu
                  disabledKeys={isTogglingActivation ? ["activation"] : []}
                  onAction={(key) => {
                    const actions: Record<
                      string,
                      (() => void | Promise<void>) | undefined
                    > = {
                      activation: () => onToggleActivation(!isActivated),
                      marketplace: onViewMarketplace,
                      unpublish: onUnpublish,
                      reset: onResetToDefault,
                      delete: onDelete,
                    };
                    actions[String(key)]?.();
                  }}
                >
                  <DropdownItem
                    id="activation"
                    textValue={isActivated ? "Disable" : "Enable"}
                  >
                    {isActivated ? (
                      <ToggleOffIcon className={iconClasses} />
                    ) : (
                      <ToggleOnIcon className={iconClasses} />
                    )}
                    <Label>{isActivated ? "Disable" : "Enable"}</Label>
                    <Description>
                      {isActivated
                        ? "Stop this workflow from running"
                        : "Allow this workflow to run"}
                    </Description>
                  </DropdownItem>

                  {showMarketplace ? (
                    <DropdownItem
                      id="marketplace"
                      textValue="View on marketplace"
                    >
                      <LinkSquare02Icon className={iconClasses} />
                      <Label>View on marketplace</Label>
                      <Description>Open on the marketplace</Description>
                    </DropdownItem>
                  ) : null}

                  {showUnpublish ? (
                    <DropdownItem id="unpublish" textValue="Unpublish">
                      <Cancel01Icon className={iconClasses} />
                      <Label>Unpublish</Label>
                      <Description>Remove from the marketplace</Description>
                    </DropdownItem>
                  ) : null}

                  {showReset ? (
                    <DropdownItem id="reset" textValue="Reset to default">
                      <ReloadIcon className={iconClasses} />
                      <Label>Reset to default</Label>
                      <Description>
                        Restore the original GAIA definition
                      </Description>
                    </DropdownItem>
                  ) : null}

                  <DropdownItem
                    id="delete"
                    textValue="Delete workflow"
                    variant="danger"
                  >
                    <Delete02Icon className={cn(iconClasses, "text-danger")} />
                    <Label>Delete workflow</Label>
                    <Description>Permanently delete this workflow</Description>
                  </DropdownItem>
                </DropdownMenu>
              </DropdownPopover>
            </Dropdown>
          </div>
        )}
      </div>

      <Controller
        name="description"
        control={control}
        render={({ field }) => (
          <TextField
            name={field.name}
            value={field.value ?? ""}
            onChange={field.onChange}
            onBlur={field.onBlur}
            isInvalid={!!errors.description}
          >
            <TextArea
              placeholder="Add a short description..."
              rows={1}
              className={inputVariants({
                variant: "bare",
                className: toneVariants({
                  tone: "dim",
                  className:
                    "resize-none text-sm field-sizing-content max-h-20",
                }),
              })}
            />
            <FieldError>{errors.description?.message}</FieldError>
          </TextField>
        )}
      />
    </div>
  );
}
