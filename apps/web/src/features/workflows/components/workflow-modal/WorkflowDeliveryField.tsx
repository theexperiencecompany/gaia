"use client";

import { WORKFLOW_DELIVERIES, WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import { Button } from "@heroui/button";
import type { WorkflowDelivery } from "@shared/api/generated";
import { cn } from "@/lib/utils";
import WorkflowSection from "./WorkflowSection";

interface WorkflowDeliveryFieldProps {
  /** null until the user picks one; a new workflow cannot be saved without it. */
  value: WorkflowDelivery | null;
  onChange: (delivery: WorkflowDelivery) => void;
  errorMessage?: string;
  isDisabled?: boolean;
}

/**
 * How each run's result reaches the user. A segmented control with no default:
 * the choice is the user's to make, so nothing is preselected.
 */
export default function WorkflowDeliveryField({
  value,
  onChange,
  errorMessage,
  isDisabled = false,
}: WorkflowDeliveryFieldProps) {
  return (
    <WorkflowSection
      label="When a run finishes"
      description={
        value
          ? WORKFLOW_DELIVERY_COPY[value].description
          : "Choose how you hear about each run."
      }
    >
      <fieldset
        aria-label="When a run finishes"
        className={cn(
          "flex gap-1 rounded-xl bg-zinc-800/60 p-1",
          errorMessage && "ring-1 ring-danger",
        )}
      >
        {WORKFLOW_DELIVERIES.map((delivery) => {
          const isSelected = value === delivery;
          return (
            <Button
              key={delivery}
              fullWidth
              radius="lg"
              variant="light"
              aria-pressed={isSelected}
              isDisabled={isDisabled}
              onPress={() => onChange(delivery)}
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
      {errorMessage && (
        <p className="px-1 text-xs text-danger">{errorMessage}</p>
      )}
    </WorkflowSection>
  );
}
