"use client";

import { Button } from "@heroui/button";
import { Kbd } from "@heroui/kbd";
import { Tooltip } from "@heroui/tooltip";

import { Target02Icon } from "@/icons";

interface GoalsSidebarProps {
  onCreateGoal?: () => void;
}

export default function GoalsSidebar({ onCreateGoal }: GoalsSidebarProps) {
  const handleCreate = () => {
    if (onCreateGoal) onCreateGoal();
  };

  return (
    <div className="flex flex-col gap-3">
      <Tooltip
        content={
          <span className="flex items-center gap-2">
            New Goal
            <Kbd className="text-[10px]">C</Kbd>
          </span>
        }
        placement="right"
      >
        <Button
          color="primary"
          size="sm"
          fullWidth
          className="mb-4 flex justify-start text-sm font-medium text-primary"
          variant="flat"
          onPress={handleCreate}
        >
          <Target02Icon width={18} height={18} />
          New Goal
        </Button>
      </Tooltip>
    </div>
  );
}
