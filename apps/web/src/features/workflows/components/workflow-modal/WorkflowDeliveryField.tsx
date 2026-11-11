"use client";

import {
  BRIEF_DELIVERY_DESCRIPTION,
  BRIEFS_OFF_DELIVERY_REASON,
  WORKFLOW_DELIVERIES,
  WORKFLOW_DELIVERY_COPY,
} from "@gaia/shared";
import { Button } from "@heroui/button";
import type { WorkflowDelivery } from "@shared/api/generated";
import Link from "next/link";
import { type Control, Controller } from "react-hook-form";
import { useBriefingScheduleSettings } from "@/features/settings/hooks/useBriefingScheduleSettings";
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
 * without one focuses the first segment and names the missing choice. "Add to
 * my brief" follows the briefing schedule and is unavailable while briefs are off.
 */
export default function WorkflowDeliveryField({
  control,
  isDisabled = false,
}: WorkflowDeliveryFieldProps) {
  const { schedule } = useBriefingScheduleSettings();
  const briefDescription = schedule?.frequency
    ? BRIEF_DELIVERY_DESCRIPTION[schedule.frequency]
    : WORKFLOW_DELIVERY_COPY.brief.description;
  const briefsOff = briefDescription === null;
  // While briefs are off, the reason line below the control speaks for "brief".
  const helperFor = (value: WorkflowDelivery | null) => {
    if (!value) return UNCHOSEN_HINT;
    if (value === "brief") return briefDescription;
    return WORKFLOW_DELIVERY_COPY[value].description;
  };

  return (
    <Controller
      name="delivery"
      control={control}
      render={({ field, fieldState }) => {
        const errorMessage = fieldState.error?.message;
        const helper = helperFor(field.value);
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
                    isDisabled={
                      isDisabled || (delivery === "brief" && briefsOff)
                    }
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
              helper && (
                <p className="px-1 pt-1 text-sm text-zinc-400">{helper}</p>
              )
            )}
            {briefsOff && (
              <p className="px-1 text-sm text-zinc-400">
                {BRIEFS_OFF_DELIVERY_REASON}{" "}
                <Link href="/settings/notifications" className="text-primary">
                  Turn on briefs
                </Link>
              </p>
            )}
          </WorkflowSection>
        );
      }}
    />
  );
}
