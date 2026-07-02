"use client";

import { ArrowUpRight01Icon, Brain02Icon, Delete02Icon } from "@icons";
import { memoryApi } from "@/features/memory/api/memoryApi";
import type { MemoryEntry } from "@/features/memory/api/types";
import { toast } from "@/lib/toast";
import { ACTION_ICON, ICON } from "../model/constants";
import type { BuildCtx, CommandItem } from "../model/types";

interface MemoryDeps {
  refetch: () => Promise<unknown>;
}

export const buildMemoryItems = (
  memories: MemoryEntry[],
  ctx: BuildCtx,
  deps: MemoryDeps,
): CommandItem[] =>
  memories
    .filter((mem): mem is MemoryEntry & { id: string } => Boolean(mem.id))
    .map((mem) => ({
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
      actions: [
        {
          id: "delete",
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
        },
      ],
    }));
