import { Task01Icon, TaskDone01Icon } from "@icons";
import type React from "react";
import { GaiaButton } from "@/components/shared/GaiaButton";

interface CopyButtonProps {
  copied: boolean;
  onPress: () => void;
}

const CopyButton: React.FC<CopyButtonProps> = ({ copied, onPress }) => (
  <GaiaButton
    className="text-xs"
    hoverTone="dim"
    size="sm"
    isIconOnly
    variant="ghost"
    onPress={onPress}
  >
    {copied ? (
      <TaskDone01Icon color="foreground" width={21} />
    ) : (
      <Task01Icon color="foreground" width={21} />
    )}
  </GaiaButton>
);

export default CopyButton;
