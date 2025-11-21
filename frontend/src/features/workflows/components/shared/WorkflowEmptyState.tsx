import { Button } from "@heroui/button";
import { Card, CardBody } from "@heroui/card";

import { WorkflowSquare03Icon } from "@/components";
import { Sparkles } from "@/icons";

interface WorkflowEmptyStateProps {
  onGenerateWorkflow?: () => void;
}

export default function WorkflowEmptyState({
  onGenerateWorkflow,
}: WorkflowEmptyStateProps) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <WorkflowSquare03Icon className="h-5 w-5 text-zinc-400" />
        <h3 className="text-lg font-semibold text-zinc-100">Workflow</h3>
      </div>
      <Card className="border-zinc-700 bg-zinc-800">
        <CardBody className="py-8 text-center">
          <div className="space-y-4">
            <div className="text-zinc-400">
              <Sparkles className="mx-auto mb-2 h-8 w-8 text-zinc-500" />
              <p className="text-sm">No workflow generated yet</p>
            </div>
            <Button
              color="primary"
              variant="flat"
              size="sm"
              onPress={onGenerateWorkflow}
              startContent={<Sparkles className="h-4 w-4" />}
            >
              Generate Workflow
            </Button>
            <p className="mx-auto max-w-sm text-xs text-zinc-500">
              AI will create a step-by-step workflow using available tools to
              help you complete this todo
            </p>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
