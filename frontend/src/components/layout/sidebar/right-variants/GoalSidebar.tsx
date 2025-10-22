"use client";

import { Checkbox } from "@heroui/checkbox";
import { Chip } from "@heroui/chip";
import { Clock } from "lucide-react";
import React from "react";

import { BookIcon1, Cancel01Icon } from "@/components/shared/icons";
import {
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
} from "@/components/ui/shadcn/sidebar";
import { NodeData } from "@/types/features/goalTypes";

interface GoalSidebarProps {
  node: NodeData | null;
  onClose: () => void;
  onToggleComplete: () => void;
}

export const GoalSidebar: React.FC<GoalSidebarProps> = ({
  node,
  onClose,
  onToggleComplete,
}) => {
  if (!node) return null;

  return (
    <div className="flex h-full flex-col">
      <SidebarHeader className="flex w-full items-end justify-end px-6 pt-4 pb-0">
        <button
          onClick={onClose}
          className="cursor-pointer rounded-lg p-2 text-zinc-400 transition-colors hover:bg-zinc-800/50 hover:text-zinc-200"
          aria-label="Close"
        >
          <Cancel01Icon className="size-4" />
        </button>
      </SidebarHeader>

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
                    <Clock width={18} />
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
                <BookIcon1 width={18} />
                Resources
              </div>
              <ul className="space-y-2 text-sm text-zinc-400">
                {node.resources.map((resource, index) => (
                  <li key={index}>
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
