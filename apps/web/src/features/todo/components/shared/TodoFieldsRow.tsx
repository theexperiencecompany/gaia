"use client";

import type { TodoModel } from "@shared/api/generated";
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
  todo: Pick<TodoModel, "priority" | "project_id" | "due_date" | "labels">;
  projects: Project[];
  onPriorityChange: (priority: PriorityType) => void;
  onProjectChange: (projectId: string) => void;
  onDateChange: (date?: string, timezone?: string) => void;
  onLabelsChange: (labels: string[]) => void;
  className?: string;
  userTimezone?: string; // User's preferred timezone
}

export default function TodoFieldsRow({
  todo,
  projects,
  onPriorityChange,
  onProjectChange,
  onDateChange,
  onLabelsChange,
  className,
  userTimezone,
}: TodoFieldsRowProps) {
  const priority = todo.priority ?? Priority.NONE;
  return (
    <div className={`flex flex-wrap gap-2 ${className || ""}`}>
      <ProjectFieldChip
        value={todo.project_id ?? undefined}
        projects={projects}
        onChange={onProjectChange}
      />
      <PriorityFieldChip
        value={priority}
        onChange={onPriorityChange}
        className={`${priority === Priority.HIGH ? "text-red-400 bg-red-400/20" : priority === Priority.MEDIUM ? "text-yellow-400 bg-yellow-400/20" : priority === Priority.LOW ? "text-blue-400 bg-blue-400/20" : "text-zinc-500"}`}
      />
      <DateFieldChip
        value={todo.due_date ?? undefined}
        onChange={onDateChange}
        timezone={userTimezone}
      />
      <LabelsFieldChip value={todo.labels ?? []} onChange={onLabelsChange} />
    </div>
  );
}
