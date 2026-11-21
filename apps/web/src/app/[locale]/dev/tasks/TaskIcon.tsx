"use client";

import { useEffect, useRef } from "react";
import { useForm } from "react-hook-form";

import WorkflowIconPicker from "@/features/workflows/components/workflow-modal/WorkflowIconPicker";
import { DEFAULT_WORKFLOW_ICON_COLOR } from "@/features/workflows/constants/workflowIconStyle";
import {
  getDefaultFormValues,
  type WorkflowFormData,
} from "@/features/workflows/schemas/workflowFormSchema";
import { GaiaMark } from "./TaskParts";
import type { Task } from "./taskModel";

/** A GAIA task's icon: the workflow icon picker, with the GAIA mark until one is chosen. */
export default function TaskIcon({
  icon,
  onChange,
}: {
  icon: Task["icon"];
  onChange: (icon: Task["icon"]) => void;
}) {
  const { control, watch } = useForm<WorkflowFormData>({
    defaultValues: {
      ...getDefaultFormValues(),
      icon: icon?.name ?? null,
      icon_color: icon?.color ?? null,
    },
  });
  const latest = useRef(onChange);
  latest.current = onChange;

  useEffect(() => {
    const subscription = watch((form) =>
      latest.current(
        form.icon
          ? {
              name: form.icon,
              color: form.icon_color ?? DEFAULT_WORKFLOW_ICON_COLOR,
            }
          : undefined,
      ),
    );
    return () => subscription.unsubscribe();
  }, [watch]);

  return (
    <WorkflowIconPicker control={control} empty={<GaiaMark size={20} />} />
  );
}
