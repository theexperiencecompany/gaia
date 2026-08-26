"use client";

import { ArrowUpRight01Icon, Brain02Icon, Delete02Icon } from "@icons";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEntry } from "@/features/memory/api/types";
import { toast } from "@/lib/toast";
import { ACTION_ICON, ICON } from "../model/constants";
import type { BuildCtx, CommandAction, CommandItem } from "../model/types";

export interface MemoryDeps {
  refetch: () => Promise<unknown>;
}

/** Build a single memory row. Search hits pass `full=false`: they carry no
 * list position, so a delete there couldn't refresh the visible list —
 * they open the memories page instead of offering a stale-feeling action. */
export function makeMemoryItem(
  mem: MemoryEntry & { id: string },
  ctx: BuildCtx,
  deps: MemoryDeps,
  full = true,
): CommandItem {
  const forget: CommandAction = {
    id: "forget",
    label: "Forget memory",
    icon: <Delete02Icon {...ACTION_ICON} />,
    destructive: true,
    run: async () => {
      const ok = await ctx.host.confirm({
        title: "Forget memory",
        message: `GAIA will stop recalling "${mem.content}". Forget it?`,
        confirmText: "Forget",
        variant: "destructive",
      });
      if (!ok) return;
      await memoryApi.deleteMemory(mem.id);
      await deps.refetch();
      toast.success("Memory forgotten");
    },
  };

  return {
    id: `memory:${mem.id}`,
    type: "memory",
    title: mem.content,
    subtitle: mem.category_path || "Memory",
    icon: <Brain02Icon {...ICON} />,
    keywords: mem.category_path,
    primary: {
      id: "open",
      label: "Open in memories",
      icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
      run: ctx.navigate("/settings/memory"),
    },
    actions: full ? [forget] : [],
  };
}

export const buildMemoryItems = (
  memories: MemoryEntry[],
  ctx: BuildCtx,
  deps: MemoryDeps,
): CommandItem[] =>
  memories
    .filter((mem): mem is MemoryEntry & { id: string } => Boolean(mem.id))
    .map((mem) => makeMemoryItem(mem, ctx, deps));
