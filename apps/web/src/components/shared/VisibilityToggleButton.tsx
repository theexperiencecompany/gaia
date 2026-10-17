import { Button } from "@heroui/button";
import { ViewIcon, ViewOffSlashIcon } from "@icons";

interface VisibilityToggleButtonProps {
  visible: boolean;
  onToggle: () => void;
  /** What is being revealed, for the aria-label ("password", "API key"). */
  subject: string;
}

/** Show/hide control for a secret input's `endContent`. */
export function VisibilityToggleButton({
  visible,
  onToggle,
  subject,
}: VisibilityToggleButtonProps) {
  return (
    <Button
      isIconOnly
      size="sm"
      variant="light"
      radius="full"
      aria-label={`${visible ? "Hide" : "Show"} ${subject}`}
      onPress={onToggle}
      className="text-zinc-500"
    >
      {visible ? <ViewOffSlashIcon size={16} /> : <ViewIcon size={16} />}
    </Button>
  );
}
