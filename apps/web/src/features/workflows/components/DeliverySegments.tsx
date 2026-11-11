"use client";

import { WORKFLOW_DELIVERY_COPY } from "@gaia/shared";
import { Button } from "@heroui/button";
import type { WorkflowDelivery } from "@shared/api/generated";
import type { Ref } from "react";
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
          <Button
            key={delivery}
            ref={index === 0 ? firstRef : undefined}
            fullWidth
            radius="lg"
            variant="light"
            aria-pressed={isSelected}
            isDisabled={isDisabled?.(delivery)}
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
  );
}
