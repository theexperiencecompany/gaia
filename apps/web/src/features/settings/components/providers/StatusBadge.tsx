import { Chip } from "@heroui/react";

interface StatusBadgeProps {
  label: string;
  /** Green when the thing it labels works, zinc when it is off. */
  active: boolean;
}

export function StatusBadge({ label, active }: StatusBadgeProps) {
  return (
    <Chip size="sm" variant="soft" color={active ? "success" : "default"}>
      <Chip.Label className="text-xs font-medium">{label}</Chip.Label>
    </Chip>
  );
}
