"use client";

import { Chip } from "@heroui/chip";
import Image from "next/image";
import { useRouter } from "next/navigation";
import type React from "react";
import { StatusGlyph } from "@/components/shared/StatusGlyph";
import type { TodayDoneItem } from "@/types/features/todayTypes";
import { formatClockTime } from "../../utils/time";

interface DoneRowProps {
  item: TodayDoneItem;
}

/** A completed item — GAIA rows click into the chat where the work happened. */
export const DoneRow: React.FC<DoneRowProps> = ({ item }) => {
  const router = useRouter();

  const openItem = () =>
    router.push(
      item.assignee === "gaia" && item.conversation_id
        ? `/c/${item.conversation_id}`
        : `/todos?todoId=${item.todo_id}`,
    );

  return (
    <div className="relative flex items-center gap-3 rounded-xl px-3 py-2 transition-colors hover:bg-zinc-900">
      {/* Stretched-button overlay: the semantic, keyboard-native click target
          for the whole row; interactive children stack above it via
          position:relative. */}
      <button
        type="button"
        aria-label={`Open ${item.title}`}
        className="absolute inset-0 cursor-pointer rounded-xl"
        onClick={openItem}
      />
      <StatusGlyph kind="done" className="shrink-0" />
      <p className="min-w-0 flex-1 truncate text-sm text-zinc-400">
        {item.title}
      </p>
      {item.assignee === "gaia" && (
        <Chip
          size="sm"
          variant="flat"
          className="shrink-0 bg-zinc-800"
          startContent={
            <Image
              alt="GAIA"
              src="/images/logos/logo.webp"
              width={14}
              height={14}
            />
          }
        >
          <span className="text-xs text-zinc-400">Done by GAIA</span>
        </Chip>
      )}
      <span className="w-16 shrink-0 text-right text-xs text-zinc-600 tabular-nums">
        {formatClockTime(item.completed_at)}
      </span>
    </div>
  );
};
