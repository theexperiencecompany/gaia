import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/react";

import { WorkflowSquare03Icon } from "@/components";
import { HeaderTitle } from "@/components/layout/headers/HeaderTitle";
import { RotateCcw, Sparkles } from "@/icons";

interface WorkflowHeaderProps {
  isRegenerating?: boolean;
  onGenerateWorkflow?: () => void;
  onRunWorkflow: () => void;
}

export default function WorkflowHeader({
  isRegenerating = false,
  onGenerateWorkflow,
  onRunWorkflow,
}: WorkflowHeaderProps) {
  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex items-center gap-2">
        <HeaderTitle
          icon={
            <WorkflowSquare03Icon width={20} height={20} color={undefined} />
          }
          text="Workflow"
        />
        {isRegenerating && (
          <div className="flex items-center gap-1 text-xs text-blue-400">
            <Sparkles className="h-3 w-3 animate-pulse" />
            <span>Regenerating...</span>
          </div>
        )}
      </div>
      <div className="flex items-center gap-2">
        <Tooltip content="Regenerate Workflow" color="foreground">
          <Button
            color="default"
            variant="flat"
            size="sm"
            onPress={onGenerateWorkflow}
            startContent={
              <RotateCcw
                className={`h-4 w-4 ${isRegenerating ? "animate-spin" : ""}`}
              />
            }
            isIconOnly
            isDisabled={isRegenerating}
            isLoading={isRegenerating}
          />
        </Tooltip>

        <Button
          color="success"
          variant="flat"
          size="sm"
          onPress={onRunWorkflow}
          className="bg-green-500/20 text-green-400 hover:bg-green-500/30"
          isDisabled={isRegenerating}
        >
          Run Workflow
        </Button>
      </div>
    </div>
  );
}
