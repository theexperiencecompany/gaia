"use client";

import { WORKFLOW_DELIVERIES, WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import { type Control, Controller } from "react-hook-form";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { cn } from "@/lib/utils";
import type { WorkflowFormData } from "../../schemas/workflowFormSchema";
import WorkflowSection from "./WorkflowSection";

const FIELD_LABEL = "When a run finishes";
const UNCHOSEN_HINT = "Choose how you hear about each run.";

interface WorkflowDeliveryFieldProps {
  control: Control<WorkflowFormData>;
  isDisabled?: boolean;
}

/**
 * How each run's result reaches the user. A segmented control with no default:
 * the choice is the user's to make, so nothing is preselected. Submitting
 * without one focuses the first segment and names the missing choice.
 */
export default function WorkflowDeliveryField({
  control,
  isDisabled = false,
}: WorkflowDeliveryFieldProps) {
  return (
    <Controller
      name="delivery"
      control={control}
      render={({ field, fieldState }) => {
        const errorMessage = fieldState.error?.message;
        return (
          <WorkflowSection label={FIELD_LABEL}>
            <fieldset
              aria-label={FIELD_LABEL}
              className={cn(
                "flex flex-col gap-1 rounded-xl bg-zinc-800/60 p-1 sm:flex-row",
                errorMessage && "ring-1 ring-danger",
              )}
            >
              {WORKFLOW_DELIVERIES.map((delivery, index) => {
                const isSelected = field.value === delivery;
                return (
                  <GaiaButton
                    key={delivery}
                    ref={index === 0 ? field.ref : undefined}
                    fullWidth
                    shape="md"
                    variant={isSelected ? "default-solid" : "ghost"}
                    tone={isSelected ? "strong" : "muted"}
                    aria-pressed={isSelected}
                    isDisabled={isDisabled}
                    onPress={() => field.onChange(delivery)}
                    className={cn("h-9 font-medium", isSelected && "shadow-sm")}
                  >
                    {WORKFLOW_DELIVERY_COPY[delivery].label}
                  </GaiaButton>
                );
              })}
            </fieldset>
            {errorMessage ? (
              <p className="px-1 pt-1 text-sm text-danger">{errorMessage}</p>
            ) : (
              <p className="px-1 pt-1 text-sm text-zinc-400">
                {field.value
                  ? WORKFLOW_DELIVERY_COPY[field.value].description
                  : UNCHOSEN_HINT}
              </p>
            )}
          </WorkflowSection>
        );
      }}
    />
  );
}
