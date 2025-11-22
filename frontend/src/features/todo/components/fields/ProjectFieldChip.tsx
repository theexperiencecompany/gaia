"use client";

import { Folder02Icon } from '@/icons';
import { Project } from "@/types/features/todoTypes";

import BaseFieldChip from "./BaseFieldChip";

interface ProjectFieldChipProps {
  value?: string;
  projects: Project[];
  onChange: (projectId: string) => void;
  className?: string;
}

export default function ProjectFieldChip({
  value,
  projects,
  onChange,
  className,
}: ProjectFieldChipProps) {
  const selectedProject = projects.find((project) => project.id === value);
  const displayValue = selectedProject?.name;

  // Create a custom display value with project color indicator
  const displayValueWithColor = selectedProject ? (
    <div className="flex items-center gap-2">
      <div
        className="h-3 w-3 flex-shrink-0 rounded-full border-0"
        style={{ backgroundColor: selectedProject.color || "#71717a" }}
      />
      <span className="truncate text-zinc-200">{selectedProject.name}</span>
    </div>
  ) : undefined;

  return (
    <BaseFieldChip
      label="Project"
      value={displayValueWithColor || displayValue}
      placeholder="Project"
      icon={!selectedProject ? <Folder02Icon size={14} /> : undefined}
      variant={selectedProject ? "primary" : "default"}
      className={className}
    >
      {({ onClose }) => (
        <div className="p-1">
          {projects.map((project) => (
            <div
              key={project.id}
              onClick={() => {
                onChange(project.id);
                onClose();
              }}
              className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-zinc-300 transition-colors hover:bg-zinc-800"
            >
              <div
                className="h-3 w-3 flex-shrink-0 rounded-full border-0"
                style={{ backgroundColor: project.color || "#71717a" }}
              />
              <span className="truncate">{project.name}</span>
            </div>
          ))}

          {/* Hint */}
          <div className="mt-1 px-3 py-2">
            <p className="text-xs text-zinc-500">
              Type{" "}
              <span className="rounded bg-zinc-800 px-1 font-mono">
                @{projects[0]?.name || "project"}
              </span>{" "}
              in title/description to select
            </p>
          </div>
        </div>
      )}
    </BaseFieldChip>
  );
}
