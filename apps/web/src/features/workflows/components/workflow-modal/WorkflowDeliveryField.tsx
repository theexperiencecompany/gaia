"use client";

import { WORKFLOW_DELIVERIES, WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import { Button } from "@heroui/button";
import { type Control, Controller } from "react-hook-form";
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
                  <Button
                    key={delivery}
                    ref={index === 0 ? field.ref : undefined}
                    fullWidth
                    radius="lg"
                    variant="light"
                    aria-pressed={isSelected}
                    isDisabled={isDisabled}
                    onPress={() => field.onChange(delivery)}
                    className={cn(
                      "h-9 font-medium",
                      isSelected
                        ? "bg-zinc-700 text-zinc-100 shadow-sm data-[hover=true]:bg-zinc-700"
                        : "text-zinc-400",
                    )}
                  >
                    {WORKFLOW_DELIVERY_COPY[delivery].label}
                  </Button>
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
