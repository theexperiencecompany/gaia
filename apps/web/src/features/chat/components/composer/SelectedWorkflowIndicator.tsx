"use client";

import { Button } from "@heroui/button";
import { motion } from "framer-motion";
import { useRouter } from "next/navigation";

import type { SelectedWorkflowData } from "@/features/chat/hooks/useWorkflowSelection";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import { Cancel01Icon } from "@/icons";

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
    <motion.div
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
        <div
          className="absolute top-4 right-4 z-20"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            isIconOnly
            size="sm"
            variant="light"
            onPress={onRemove}
            className="text-zinc-400 hover:text-zinc-200"
          >
            <Cancel01Icon className="h-4 w-4" />
          </Button>
        </div>
      )}
    </motion.div>
  );
}
