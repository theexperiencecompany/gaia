"use client";

import { Checkbox } from "@heroui/checkbox";
import { Chip } from "@heroui/chip";
import { Book01Icon, Timer02Icon } from "@icons";
import type React from "react";
import { SidebarContent, SidebarFooter } from "@/components/ui/sidebar";
import type { NodeData } from "@/types/features/goalTypes";

interface GoalSidebarProps {
  node: NodeData | null;
  onToggleComplete: () => void;
}

export const GoalSidebar: React.FC<GoalSidebarProps> = ({
  node,
  onToggleComplete,
}) => {
  if (!node) return null;

  return (
    <div className="flex h-full flex-col">
      <SidebarContent className="flex-1 overflow-y-auto px-6">
        <div className="space-y-4 pt-4">
          {/* Title Section */}
          <div className="space-y-3">
            <h1
              className={`text-2xl leading-tight font-medium transition-colors ${
                node.isComplete ? "text-zinc-500 line-through" : "text-zinc-100"
              }`}
            >
              {node.label || node.title}
            </h1>

            {/* Details */}
            {node.details && node.details.length > 0 && (
              <p
                className={`text-sm leading-relaxed ${
                  node.isComplete ? "text-zinc-600" : "text-zinc-400"
                }`}
              >
                {node.details.join(", ")}
              </p>
            )}
          </div>

          {/* Chips Section */}
          <div className="space-y-3">
            {node.estimatedTime && (
              <Chip
                color="primary"
                size="lg"
                startContent={
                  <div className="flex items-center gap-1 text-sm">
                    <Timer02Icon width={18} />
                    <span>Estimated Time:</span>
                  </div>
                }
                variant="flat"
              >
                <span className="pl-1 text-sm text-white">
                  {node.estimatedTime}
                </span>
              </Chip>
            )}

            <Chip
              color="success"
              size="lg"
              startContent={
                <Checkbox
                  isSelected={node.isComplete ?? false}
                  onValueChange={onToggleComplete}
                  color="success"
                  radius="full"
                  lineThrough
                >
                  <span className="text-sm">Mark as Complete</span>
                </Checkbox>
              }
              variant="flat"
            />
          </div>

          {/* Resources Section */}
          {node.resources && node.resources.length > 0 && (
            <div className="rounded-xl bg-zinc-800/40 p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium text-zinc-200">
                <Book01Icon width={18} />
                Resources
              </div>
              <ul className="space-y-2 text-sm text-zinc-400">
                {node.resources.map((resource) => (
                  <li key={resource}>
                    <a
                      className="underline decoration-zinc-600 underline-offset-4 transition-colors hover:text-primary hover:decoration-primary"
                      href={`https://www.google.com/search?q=${resource.replace(
                        / /g,
                        "+",
                      )}`}
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {resource}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </SidebarContent>

      <SidebarFooter className="px-6 py-6">
        <div className="text-center text-xs text-zinc-600">
          {node.type && <div className="capitalize">Type: {node.type}</div>}
        </div>
      </SidebarFooter>
    </div>
  );
};
