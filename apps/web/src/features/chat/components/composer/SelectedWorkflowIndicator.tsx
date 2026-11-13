"use client";

import { Cancel01Icon } from "@icons";
import * as m from "motion/react-m";
import { useRouter } from "next/navigation";
import { GaiaButton } from "@/components/shared/GaiaButton";
import type { SelectedWorkflowData } from "@/features/chat/hooks/useWorkflowSelection";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";

interface SelectedWorkflowIndicatorProps {
  workflow: SelectedWorkflowData | null;
  onRemove?: () => void;
}

export default function SelectedWorkflowIndicator({
  workflow,
  onRemove,
}: SelectedWorkflowIndicatorProps) {
  const router = useRouter();

  // Return null if no workflow is selected
  if (!workflow) {
    return null;
  }

  const handleWorkflowClick = () => {
    if (workflow.id) {
      router.push(`/workflows/${workflow.id}`);
    }
  };

  return (
    <m.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="relative m-3 w-80 rounded-3xl border-2 border-zinc-700"
    >
      <UnifiedWorkflowCard
        title={workflow.title}
        description={workflow.description}
        steps={workflow.steps}
        variant="user"
        primaryAction="none"
        onCardClick={handleWorkflowClick}
        showExecutions={false}
      />
      {onRemove && (
        <div className="absolute top-4 right-4 z-20">
          <GaiaButton
            isIconOnly
            size="sm"
            variant="ghost"
            onPress={onRemove}
            tone="muted"
            hoverTone="bright"
          >
            <Cancel01Icon className="h-4 w-4" />
          </GaiaButton>
        </div>
      )}
    </m.div>
  );
}
