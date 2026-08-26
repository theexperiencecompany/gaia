"use client";

import { ArrowUpRight01Icon, Cancel01Icon, PlugSocketIcon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { Integration } from "@/features/integrations/types";
import { ACTION_ICON } from "../model/constants";
import type { BuildCtx, CommandAction, CommandItem } from "../model/types";

interface IntegrationDeps {
  connectIntegration: (id: string) => Promise<unknown>;
  disconnectIntegration: (id: string) => Promise<void>;
}

/** Only connected / created / failed integrations are surfaced. */
export const buildIntegrationItems = (
  integrations: Integration[],
  ctx: BuildCtx,
  deps: IntegrationDeps,
): CommandItem[] =>
  integrations
    .filter(
      (int) =>
        int.status === "connected" ||
        int.status === "created" ||
        int.status === "error",
    )
    .map((int) => {
      // "created" = set up but never connected; "error" = connection failed.
      // Each status maps to exactly one of Connect / Disconnect.
      const isConnected = int.status === "connected";
      const canConnect = int.status === "created" || int.status === "error";
      const connect: CommandAction = {
        id: "connect",
        label: int.status === "error" ? "Reconnect" : "Connect",
        icon: <PlugSocketIcon {...ACTION_ICON} />,
        run: async () => {
          ctx.host.close();
          await deps.connectIntegration(int.id);
        },
      };
      const disconnect: CommandAction = {
        id: "disconnect",
        label: "Disconnect",
        icon: <Cancel01Icon {...ACTION_ICON} />,
        destructive: true,
        run: async () => {
          const ok = await ctx.host.confirm({
            title: "Disconnect integration",
            message: `Disconnect ${int.name}?`,
            confirmText: "Disconnect",
            variant: "destructive",
          });
          if (!ok) return;
          await deps.disconnectIntegration(int.id);
        },
      };
      const actions: CommandAction[] = [];
      if (canConnect) actions.push(connect);
      if (isConnected) actions.push(disconnect);

      return {
        id: `integration:${int.id}`,
        type: "integration",
        title: int.name,
        subtitle:
          int.category + (int.toolCount ? ` · ${int.toolCount} tools` : ""),
        icon: getToolCategoryIcon(
          int.id,
          { size: 18, width: 18, height: 18, showBackground: false },
          int.iconUrl,
        ),
        keywords: `${int.category} ${int.status}`,
        dot:
          int.status === "error"
            ? { color: "yellow", label: "Connection failed" }
            : isConnected
              ? { color: "green", label: "Connected" }
              : undefined,
        primary: {
          id: "open",
          label: "Open settings",
          icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
          run: ctx.navigate(`/integrations?id=${encodeURIComponent(int.id)}`),
        },
        actions,
      };
    });
