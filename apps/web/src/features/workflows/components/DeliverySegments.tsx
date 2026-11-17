"use client";

import { WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import type { WorkflowDelivery } from "@shared/api/generated";
import type { Ref } from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { cn } from "@/lib/utils";

interface DeliverySegmentsProps<D extends WorkflowDelivery> {
  label: string;
  deliveries: readonly D[];
  /** null when nothing is chosen yet: no segment is preselected. */
  value: D | null;
  onChange: (delivery: D) => void;
  isDisabled?: (delivery: D) => boolean;
  /** Focus target for the first segment, so a form can point at a missing choice. */
  firstRef?: Ref<HTMLButtonElement>;
  isInvalid?: boolean;
  className?: string;
}

/** A segmented choice of how a workflow's results reach the user. */
export function DeliverySegments<D extends WorkflowDelivery>({
  label,
  deliveries,
  value,
  onChange,
  isDisabled,
  firstRef,
  isInvalid = false,
  className,
}: DeliverySegmentsProps<D>) {
  return (
    <fieldset
      aria-label={label}
      className={cn(
        "flex flex-col gap-1 rounded-xl bg-zinc-800/60 p-1 sm:flex-row",
        isInvalid && "ring-1 ring-danger",
        className,
      )}
    >
      {deliveries.map((delivery, index) => {
        const isSelected = value === delivery;
        return (
          <GaiaButton
            key={delivery}
            ref={index === 0 ? firstRef : undefined}
            fullWidth
            shape="md"
            variant={isSelected ? "default-solid" : "ghost"}
            tone={isSelected ? "strong" : "muted"}
            aria-pressed={isSelected}
            isDisabled={isDisabled?.(delivery)}
            onPress={() => onChange(delivery)}
            className={cn("h-9 font-medium", isSelected && "shadow-sm")}
          >
            {WORKFLOW_DELIVERY_COPY[delivery].label}
          </GaiaButton>
        );
      })}
    </fieldset>
  );
}
