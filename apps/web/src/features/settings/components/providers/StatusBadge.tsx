import { Chip } from "@heroui/chip";

interface StatusBadgeProps {
  label: string;
  /** Green when the thing it labels works, zinc when it is off. */
  active: boolean;
}

export function StatusBadge({ label, active }: StatusBadgeProps) {
  return (
    <Chip
      size="sm"
      variant="flat"
      color={active ? "success" : "default"}
      classNames={{ content: "text-xs font-medium" }}
    >
      {label}
    </Chip>
  );
}
