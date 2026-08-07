"use client";

import { Spinner } from "@heroui/spinner";
import { useRouter } from "next/navigation";
import type React from "react";
import { StatusGlyph } from "@/components/shared/StatusGlyph";
import type { TodayInFlightItem } from "@/types/features/todayTypes";
import { formatClockTime } from "../../utils/time";

interface InFlightRowProps {
  item: TodayInFlightItem;
}

/** GAIA work currently queued or running — click into the live run's chat. */
export const InFlightRow: React.FC<InFlightRowProps> = ({ item }) => {
  const router = useRouter();
  const startedAt = formatClockTime(item.started_at);

  return (
    <div
      className="flex cursor-pointer items-center gap-3 rounded-xl px-3 py-2 transition-colors hover:bg-zinc-900"
      onClick={() =>
        router.push(
          item.conversation_id
            ? `/c/${item.conversation_id}`
            : `/todos?todoId=${item.todo_id}`,
        )
      }
    >
      {item.execution_status === "queued" ? (
        <StatusGlyph kind="queued" className="shrink-0" />
      ) : (
        <Spinner size="sm" color="default" className="shrink-0 scale-90" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium text-zinc-200">
          {item.title}
        </p>
        {item.serves && (
          <p className="truncate text-xs text-zinc-500">{item.serves}</p>
        )}
      </div>
      <span className="shrink-0 text-xs text-zinc-600 tabular-nums">
        {item.execution_status === "queued"
          ? "queued"
          : startedAt
            ? `started ${startedAt}`
            : "running"}
      </span>
    </div>
  );
};
