import type { AppStatusChipStatus } from "@/shared/components/ui/app-status-chip";
import { WORKFLOW_COLORS } from "./colors";

export type ExecutionStatus = "running" | "success" | "failed";

export type ActivationStatus = "activated" | "deactivated";

export interface WorkflowStatusDescriptor {
  /** Maps to the AppStatusChip status enum. */
  chipStatus: AppStatusChipStatus;
  /** Human-readable label used in chips and badges. */
  label: string;
  /** Foreground colour for inline status indicators (e.g. dot + label rows). */
  fgColor: string;
  /** Background colour for inline status indicators (soft tinted). */
  bgColor: string;
}

export const ACTIVATION_STATUS: Record<
  ActivationStatus,
  WorkflowStatusDescriptor
> = {
  activated: {
    chipStatus: "active",
    label: "Activated",
    fgColor: WORKFLOW_COLORS.successText,
    bgColor: WORKFLOW_COLORS.successBg,
  },
  deactivated: {
    chipStatus: "danger",
    label: "Deactivated",
    fgColor: WORKFLOW_COLORS.dangerText,
    bgColor: WORKFLOW_COLORS.dangerBg,
  },
};

export const EXECUTION_STATUS: Record<
  ExecutionStatus,
  WorkflowStatusDescriptor
> = {
  success: {
    chipStatus: "success",
    label: "Success",
    fgColor: WORKFLOW_COLORS.successText,
    bgColor: WORKFLOW_COLORS.successBg,
  },
  failed: {
    chipStatus: "danger",
    label: "Failed",
    fgColor: WORKFLOW_COLORS.dangerText,
    bgColor: WORKFLOW_COLORS.dangerBg,
  },
  running: {
    chipStatus: "running",
    label: "Running",
    fgColor: WORKFLOW_COLORS.primary,
    bgColor: WORKFLOW_COLORS.primarySubtleAlt,
  },
};
