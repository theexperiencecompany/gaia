import * as m from "motion/react-m";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import UnifiedWorkflowCard from "@/features/workflows/components/shared/UnifiedWorkflowCard";
import { COLUMN_CLASSES } from "./UseCaseSection.helpers";

interface WorkflowsGridProps {
  workflows: Workflow[];
  disableCentering?: boolean;
  noMaxWidth?: boolean;
  setShowUseCases?: React.Dispatch<React.SetStateAction<boolean>>;
  showDescriptionAsTooltip?: boolean;
  useBlurEffect?: boolean;
  columns: number;
}

export function WorkflowsGrid({
  workflows,
  disableCentering,
  noMaxWidth,
  setShowUseCases,
  showDescriptionAsTooltip,
  useBlurEffect,
  columns,
}: WorkflowsGridProps) {
  return (
    <m.div
      key="workflows"
      className={`${disableCentering ? "" : "mx-auto"} grid ${noMaxWidth ? "" : setShowUseCases ? "max-w-5xl" : "max-w-7xl"} grid-cols-1 gap-6 sm:grid-cols-2 ${COLUMN_CLASSES[columns] ?? COLUMN_CLASSES[4]}`}
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -20 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
    >
      {workflows.map((workflow: Workflow, index: number) => (
        <m.div
          key={workflow.id}
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{
            duration: 0.3,
            delay: index * 0.05,
            ease: "easeOut",
          }}
        >
          <UnifiedWorkflowCard
            workflow={workflow}
            showDescriptionAsTooltip={showDescriptionAsTooltip}
            variant="user"
            primaryAction="run"
            useBlurEffect={useBlurEffect}
          />
        </m.div>
      ))}
    </m.div>
  );
}
