"use client";

import { Button } from "@heroui/button";
import { X } from "lucide-react";
import { motion } from "framer-motion";
import { useState } from "react";
import { useRouter } from "next/navigation";

import { SelectedWorkflowData } from "@/features/chat/hooks/useWorkflowSelection";
import BaseWorkflowCard from "@/features/workflows/components/shared/BaseWorkflowCard";

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

  // Create header right content with remove button
  const headerRight = onRemove ? (
    <Button
      isIconOnly
      size="sm"
      variant="light"
      onPress={() => onRemove()}
      className="text-zinc-400 hover:text-zinc-200"
    >
      <X className="h-4 w-4" />
    </Button>
  ) : undefined;

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="m-3 w-80 rounded-2xl border-2 border-zinc-700"
    >
      <BaseWorkflowCard
        title={workflow.title}
        description={workflow.description}
        steps={workflow.steps}
        headerRight={headerRight}
        showArrowIcon={true}
        hideExecutions
        onClick={handleWorkflowClick}
      />
    </motion.div>
  );
}
