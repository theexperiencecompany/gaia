import { Button } from "@heroui/button";
import { Task01Icon, TaskDone01Icon } from "@icons";
import type React from "react";

interface CopyButtonProps {
  copied: boolean;
  onPress: () => void;
}

const CopyButton: React.FC<CopyButtonProps> = ({ copied, onPress }) => (
  <Button
    className="text-xs text-foreground hover:text-gray-300"
    size="sm"
    isIconOnly
    variant="light"
    onPress={onPress}
  >
    {copied ? (
      <TaskDone01Icon color="foreground" width={21} />
    ) : (
      <Task01Icon color="foreground" width={21} />
    )}
  </Button>
);

export default CopyButton;
