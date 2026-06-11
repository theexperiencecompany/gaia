"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Spinner } from "@heroui/spinner";
import { Tooltip } from "@heroui/tooltip";
import { Delete02Icon, PencilEdit02Icon } from "@icons";
import { formatDistanceToNow } from "date-fns";
import { useState } from "react";
import { memoryApi } from "@/features/memory/api/memoryApi";
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
  const [expanded, setExpanded] = useState(false);
  const [history, setHistory] = useState<MemoryEntry[] | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const toggleHistory = async () => {
    if (expanded) {
      setExpanded(false);
      return;
    }
    setExpanded(true);
    if (history || !memory.id) return;
    setLoadingHistory(true);
    try {
      const result = await memoryApi.getHistory(memory.id);
      // Older versions only — the current row already shows the latest.
      setHistory(result.memories.filter((m) => !m.is_latest));
    } catch {
      setHistory([]);
    } finally {
      setLoadingHistory(false);
    }
  };

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
          {memory.version > 1 && (
            <Chip
              as="button"
              size="sm"
              variant="flat"
              onClick={toggleHistory}
              classNames={{
                base: "h-5 cursor-pointer bg-zinc-800 data-[hover=true]:bg-zinc-700",
                content: "px-1.5 text-xs text-zinc-400",
              }}
            >
              v{memory.version}
              {expanded ? " · hide history" : " · history"}
            </Chip>
          )}
        </div>

        {expanded && (
          <div className="mt-3 pl-1">
            {loadingHistory ? (
              <Spinner size="sm" />
            ) : history && history.length > 0 ? (
              <div className="relative ml-1.5">
                <div className="absolute left-0 top-0 h-full w-px bg-zinc-700" />
                {history.map((older, i) => (
                  <div key={older.id} className="relative mb-3 pl-4 last:mb-0">
                    <span
                      className={`absolute left-[-3px] top-1.5 size-[7px] rounded-full border border-zinc-600 ${i === 0 ? "bg-zinc-500" : "bg-zinc-800"}`}
                    />
                    <div className="flex items-baseline gap-2">
                      <span className="shrink-0 text-xs font-medium text-zinc-500">
                        v{older.version}
                      </span>
                      {older.relation_type && (
                        <span className="shrink-0 rounded bg-zinc-800 px-1 py-0.5 text-[10px] text-zinc-600">
                          {older.relation_type}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">
                      {older.content}
                    </p>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-zinc-600">No earlier versions.</p>
            )}
          </div>
        )}
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
