"use client";

import DateFieldChip from "@/features/todo/components/fields/DateFieldChip";
import LabelsFieldChip from "@/features/todo/components/fields/LabelsFieldChip";
import PriorityFieldChip from "@/features/todo/components/fields/PriorityFieldChip";
import ProjectFieldChip from "@/features/todo/components/fields/ProjectFieldChip";
import {
  Priority,
  type Priority as PriorityType,
  type Project,
} from "@/types/features/todoTypes";

interface TodoFieldsRowProps {
  priority: PriorityType;
  projectId?: string;
  projects: Project[];
  dueDate?: string;
  dueDateTimezone?: string;
  labels: string[];
  onPriorityChange: (priority: PriorityType) => void;
  onProjectChange: (projectId: string) => void;
  onDateChange: (date?: string, timezone?: string) => void;
  onLabelsChange: (labels: string[]) => void;
  className?: string;
  userTimezone?: string; // User's preferred timezone
}

export default function TodoFieldsRow({
  priority,
  projectId,
  projects,
  dueDate,
  dueDateTimezone: _dueDateTimezone,
  labels,
  onPriorityChange,
  onProjectChange,
  onDateChange,
  onLabelsChange,
  className,
  userTimezone,
}: TodoFieldsRowProps) {
  return (
    <div className={`flex flex-wrap gap-2 ${className || ""}`}>
      <ProjectFieldChip
        value={projectId}
        projects={projects}
        onChange={onProjectChange}
      />
      <PriorityFieldChip
        value={priority}
        onChange={onPriorityChange}
        className={`${priority === Priority.HIGH ? "text-red-400 bg-red-400/20" : priority === Priority.MEDIUM ? "text-yellow-400 bg-yellow-400/20" : priority === Priority.LOW ? "text-blue-400 bg-blue-400/20" : "text-zinc-500"}`}
      />
      <DateFieldChip
        value={dueDate}
        onChange={onDateChange}
        timezone={userTimezone}
      />
      <LabelsFieldChip value={labels} onChange={onLabelsChange} />
    </div>
  );
}
