import { Chip } from "heroui-native";

type ChipProps = React.ComponentProps<typeof Chip>;

const STATUS_TONE_MAP = {
  default: "default",
  active: "success",
  connected: "success",
  success: "success",
  pending: "warning",
  inactive: "default",
  draft: "default",
  warning: "warning",
  danger: "danger",
  error: "danger",
} as const;

const STATUS_LABEL_MAP = {
  default: "Status",
  active: "Active",
  connected: "Connected",
  success: "Success",
  pending: "Pending",
  inactive: "Inactive",
  draft: "Draft",
  warning: "Warning",
  danger: "Error",
  error: "Error",
} as const;

export type AppStatusChipStatus = keyof typeof STATUS_TONE_MAP;

export interface AppStatusChipProps
  extends Omit<ChipProps, "children" | "color" | "variant"> {
  label?: string;
  status?: AppStatusChipStatus;
  tone?: ChipProps["color"];
  variant?: ChipProps["variant"];
  startContent?: React.ReactNode;
}

export function AppStatusChip({
  label,
  status = "default",
  tone,
  variant = "soft",
  size = "sm",
  startContent,
  ...chipProps
}: AppStatusChipProps) {
  return (
    <Chip
      {...chipProps}
      size={size}
      variant={variant}
      color={tone ?? STATUS_TONE_MAP[status]}
      animation="disable-all"
    >
      {startContent}
      <Chip.Label>{label ?? STATUS_LABEL_MAP[status]}</Chip.Label>
    </Chip>
  );
}
