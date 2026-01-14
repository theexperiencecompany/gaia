"use client";

import { Folder02Icon } from "@/icons";
import type { Project } from "@/types/features/todoTypes";

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
      <div style={{ color: selectedProject.color || "#71717a" }}>
        <Folder02Icon width={18} height={18} />
      </div>
      <span className="truncate text-foreground-200">{selectedProject.name}</span>
    </div>
  ) : undefined;

  return (
    <BaseFieldChip
      label="Project"
      value={displayValueWithColor || displayValue}
      placeholder="Project"
      icon={selectedProject ? undefined : <Folder02Icon size={14} />}
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
              className="flex cursor-pointer items-center gap-2 rounded-md px-3 py-2 text-foreground-300 transition-colors hover:bg-surface-200"
            >
              <div style={{ color: project.color || "#71717a" }}>
                <Folder02Icon width={18} height={18} />
              </div>
              <span className="truncate">{project.name}</span>
            </div>
          ))}

          {/* Hint */}
          <div className="mt-1 px-3 py-2">
            <p className="text-xs text-foreground-500">
              Type{" "}
              <span className="rounded bg-surface-200 px-1 font-mono">
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
