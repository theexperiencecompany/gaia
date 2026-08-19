import * as m from "motion/react-m";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import type { UseCase } from "@/types/features/workflowTypes";
import { COLUMN_CLASSES } from "./UseCaseSection.helpers";

interface UseCaseGridProps {
  useCases: UseCase[];
  category: string;
  disableCentering?: boolean;
  noMaxWidth?: boolean;
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
  showDescriptionAsTooltip?: boolean;
  useBlurEffect?: boolean;
  columns: number;
}

export function UseCaseGrid({
  useCases,
  category,
  disableCentering,
  noMaxWidth,
  setShowUseCases,
  showDescriptionAsTooltip,
  useBlurEffect,
  columns,
}: UseCaseGridProps) {
  return (
    <m.div
      key={category}
      className={`${disableCentering ? "" : "mx-auto"} grid ${noMaxWidth ? "" : setShowUseCases ? "max-w-5xl" : "max-w-7xl"} grid-cols-1 gap-6 sm:grid-cols-2 ${COLUMN_CLASSES[columns] ?? COLUMN_CLASSES[4]}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {useCases.map((useCase: UseCase, index: number) => (
        <m.div
          key={useCase.published_id}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.3,
            delay: index * 0.05,
            ease: "easeOut",
          }}
        >
          <UnifiedWorkflowCard
            showDescriptionAsTooltip={showDescriptionAsTooltip}
            title={useCase.title || ""}
            description={useCase.description || ""}
            actionType={useCase.action_type || "prompt"}
            prompt={useCase.prompt}
            slug={useCase.slug}
            href={useCase.slug ? `/use-cases/${useCase.slug}` : undefined}
            steps={useCase.steps}
            icon={useCase.icon}
            iconColor={useCase.icon_color}
            systemWorkflowKey={useCase.system_workflow_key}
            triggerConfig={useCase.trigger_config}
            creator={useCase.creator}
            totalExecutions={useCase.total_executions || 0}
            showExecutions={true}
            useBlurEffect={useBlurEffect}
            variant="explore"
            primaryAction={
              useCase.action_type === "prompt" ? "insert-prompt" : "create"
            }
          />
        </m.div>
      ))}
    </m.div>
  );
}
