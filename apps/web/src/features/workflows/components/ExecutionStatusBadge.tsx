import { Chip } from "@heroui/chip";
import { AlertCircleIcon, CheckmarkCircle02Icon, Loading03Icon } from "@icons";

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
          size="sm"
          color="success"
          variant="flat"
          radius="sm"
          startContent={<CheckmarkCircle02Icon className="h-3 w-3" />}
        >
          Success
        </Chip>
      );
    case "failed":
      return (
        <Chip
          size="sm"
          color="danger"
          variant="flat"
          radius="sm"
          startContent={<AlertCircleIcon className="h-3 w-3" />}
        >
          Failed
        </Chip>
      );
    case "skipped":
      return (
        <Chip size="sm" color="default" variant="flat" radius="sm">
          Skipped
        </Chip>
      );
    case "running":
      return (
        <Chip
          size="sm"
          color="primary"
          radius="sm"
          variant="flat"
          startContent={
            <div className="animate-spin">
              <Loading03Icon className="h-3 w-3" />
            </div>
          }
        >
          Running
        </Chip>
      );
  }
}
