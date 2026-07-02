"use client";

import { ArrowUpRight01Icon, Settings01Icon } from "@icons";
import { settingsPageItems } from "@/features/settings/config/settingsConfig";
import { ACTION_ICON, ICON } from "../model/constants";
import type { BuildCtx, CommandItem } from "../model/types";

// These have their own top-level Browse categories, so don't duplicate them here.
const EXCLUDED = new Set(["desktop", "memory", "notifications"]);

export const buildSettingsItems = (ctx: BuildCtx): CommandItem[] =>
  settingsPageItems
    .filter((item) => item.href && !EXCLUDED.has(item.key))
    .map((item) => {
      const Icon = item.icon;
      return {
        id: `setting:${item.key}`,
        type: "page" as const,
        title: item.label,
        icon: Icon ? <Icon {...ICON} /> : <Settings01Icon {...ICON} />,
        keywords: "settings",
        primary: {
          id: "open",
          label: `Open ${item.label}`,
          icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
          run: ctx.navigate(item.href as string),
        },
        actions: [],
      };
    });
