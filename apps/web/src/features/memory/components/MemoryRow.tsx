"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Tooltip } from "@heroui/tooltip";
import { Delete02Icon, PencilEdit02Icon } from "@icons";
import { formatDistanceToNow } from "date-fns";
import type { MemoryEntry } from "@/features/memory/api/types";
import { cn } from "@/lib/utils";

interface MemoryRowProps {
  memory: MemoryEntry;
  showCategory?: boolean;
  isDeleting?: boolean;
  onEdit: (memory: MemoryEntry) => void;
  onForget: (memory: MemoryEntry) => void;
}

function importanceColor(importance: number): string {
  if (importance >= 0.7) return "bg-primary";
  if (importance >= 0.4) return "bg-zinc-400";
  return "bg-zinc-600";
}

export function MemoryRow({
  memory,
  showCategory = false,
  isDeleting = false,
  onEdit,
  onForget,
}: MemoryRowProps) {
  const timestamp = memory.created_at ?? memory.mentioned_at;

  return (
    <div className="group flex items-start gap-3 px-4 py-3 transition-colors hover:bg-white/5">
      <Tooltip
        content={`Importance ${Math.round(memory.importance * 100)}%`}
        placement="left"
        closeDelay={0}
      >
        <span
          className={cn(
            "mt-1.5 size-2 shrink-0 rounded-full",
            importanceColor(memory.importance),
          )}
        />
      </Tooltip>

      <div className="min-w-0 flex-1">
        <p className="text-sm text-zinc-100">{memory.content}</p>
        <div className="mt-1 flex items-center gap-2 text-xs text-zinc-500">
          {timestamp && (
            <span>
              {formatDistanceToNow(new Date(timestamp), { addSuffix: true })}
            </span>
          )}
          {showCategory && memory.category_path && (
            <Chip
              size="sm"
              variant="flat"
              classNames={{
                base: "h-5 bg-zinc-800",
                content: "px-1.5 text-xs text-zinc-400",
              }}
            >
              {memory.category_path}
            </Chip>
          )}
          {memory.version > 1 && <span>v{memory.version}</span>}
        </div>
      </div>

      <div className="flex shrink-0 gap-1 opacity-0 transition-opacity group-hover:opacity-100">
        <Button
          isIconOnly
          size="sm"
          variant="light"
          aria-label="Edit memory"
          onPress={() => onEdit(memory)}
        >
          <PencilEdit02Icon className="size-4 text-zinc-400" />
        </Button>
        <Button
          isIconOnly
          size="sm"
          variant="light"
          color="danger"
          aria-label="Forget memory"
          isLoading={isDeleting}
          onPress={() => onForget(memory)}
        >
          <Delete02Icon className="size-4" />
        </Button>
      </div>
    </div>
  );
}
