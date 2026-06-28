"use client";

import {
  ArrowUpRight01Icon,
  Delete02Icon,
  PlayIcon,
  ToggleOffIcon,
  ToggleOnIcon,
  ZapIcon,
} from "@icons";
import type { Workflow } from "@/features/workflows/api/workflowApi";
import type { WorkflowActions } from "@/features/workflows/hooks/useWorkflowActions";
import { ACTION_ICON, ICON } from "../model/constants";
import type { BuildCtx, CommandItem } from "../model/types";

export const buildWorkflowItems = (
  workflows: Workflow[],
  ctx: BuildCtx,
  actions: WorkflowActions,
): CommandItem[] =>
  workflows.map((wf) => ({
    id: `workflow:${wf.id}`,
    type: "workflow",
    title: wf.title,
    subtitle:
      wf.description || `${wf.trigger_config?.type ?? "manual"} trigger`,
    icon: <ZapIcon {...ICON} />,
    keywords: `${wf.trigger_config?.type ?? ""} ${wf.total_executions} runs`,
    dot: wf.activated
      ? { color: "green", label: "Active" }
      : { color: "yellow", label: "Paused" },
    primary: {
      id: "open",
      label: "Open workflow",
      icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
      run: ctx.navigate(`/workflows?id=${wf.id}`),
    },
    actions: [
      {
        id: "run",
        label: "Run now",
        icon: <PlayIcon {...ACTION_ICON} />,
        run: async () => {
          ctx.host.close();
          await actions.run(wf.id);
        },
      },
      {
        id: "toggle",
        label: wf.activated ? "Deactivate" : "Activate",
        icon: wf.activated ? (
          <ToggleOffIcon {...ACTION_ICON} />
        ) : (
          <ToggleOnIcon {...ACTION_ICON} />
        ),
        run: () => actions.setActivated(wf.id, wf.activated),
      },
      {
        id: "delete",
        label: "Delete workflow",
        icon: <Delete02Icon {...ACTION_ICON} />,
        destructive: true,
        run: async () => {
          const ok = await ctx.host.confirm({
            title: "Delete workflow",
            message: `Delete "${wf.title}"? This cannot be undone.`,
            confirmText: "Delete",
            variant: "destructive",
          });
          if (!ok) return;
          await actions.remove(wf.id);
        },
      },
    ],
  }));
