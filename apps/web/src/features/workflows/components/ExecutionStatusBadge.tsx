import { Chip, Spinner } from "@heroui/react";
import { AlertCircleIcon, CheckmarkCircle02Icon } from "@icons";
import { shapeVariants } from "@/components/shared/shape";

import type { WorkflowExecution } from "../types/workflowExecutionTypes";

export function ExecutionStatusBadge({
  status,
}: {
  status: WorkflowExecution["status"];
}) {
  switch (status) {
    case "success":
      return (
        <Chip
          className={shapeVariants({ shape: "sm" })}
          size="sm"
          color="success"
          variant="soft"
        >
          <CheckmarkCircle02Icon className="h-3 w-3" />
          <Chip.Label>Success</Chip.Label>
        </Chip>
      );
    case "failed":
      return (
        <Chip
          className={shapeVariants({ shape: "sm" })}
          size="sm"
          color="danger"
          variant="soft"
        >
          <AlertCircleIcon className="h-3 w-3" />
          <Chip.Label>Failed</Chip.Label>
        </Chip>
      );
    case "skipped":
      return (
        <Chip
          className={shapeVariants({ shape: "sm" })}
          size="sm"
          color="default"
          variant="soft"
        >
          <Chip.Label>Skipped</Chip.Label>
        </Chip>
      );
    case "running":
      return (
        <Chip
          className={shapeVariants({ shape: "sm" })}
          size="sm"
          color="accent"
          variant="soft"
        >
          <Spinner size="sm" color="current" className="size-3" />
          <Chip.Label>Running</Chip.Label>
        </Chip>
      );
  }
}
