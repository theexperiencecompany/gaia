"use client";

import { ArrowUpRight01Icon, Cancel01Icon, PlugSocketIcon } from "@icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { Integration } from "@/features/integrations/types";
import { byConnectionStateThenName } from "@/features/integrations/utils/catalog";
import { ACTION_ICON } from "../model/constants";
import type { BuildCtx, CommandAction, CommandItem } from "../model/types";

interface IntegrationDeps {
  connectIntegration: (id: string) => Promise<unknown>;
  disconnectIntegration: (id: string) => Promise<void>;
}

/**
 * Cap on catalog rows surfaced in the palette. The full /integrations/me
 * catalog can be large; anything past the cap stays reachable on the
 * integrations page (sorted connection-state-first so connected and
 * featured entries are never the ones cut).
 */
const MAX_ITEMS = 60;

const DOT: Record<Integration["status"], CommandItem["dot"] | undefined> = {
  connected: { color: "green", label: "Connected" },
  error: { color: "yellow", label: "Connection failed" },
  expired: { color: "yellow", label: "Connection expired" },
  created: undefined,
  not_connected: undefined,
};

/** Build one row; `connectable` rows put the connect verb first. */
function buildIntegrationItem(
  int: Integration,
  ctx: BuildCtx,
  deps: IntegrationDeps,
): CommandItem {
  const connectLabel =
    int.status === "error" || int.status === "expired"
      ? "Reconnect"
      : "Connect";
  const connect: CommandAction = {
    id: "connect",
    label: connectLabel,
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
  const open: CommandAction = {
    id: "open",
    label: "Open settings",
    icon: <ArrowUpRight01Icon {...ACTION_ICON} />,
    run: ctx.navigate(`/integrations?id=${encodeURIComponent(int.id)}`),
  };

  // Connected → manage it (open first). Everything else → connect verb
  // first, settings as the secondary path.
  const connectable = int.status !== "connected";
  return {
    id: `integration:${int.id}`,
    type: "integration",
    title: int.name,
    subtitle: int.category + (int.toolCount ? ` · ${int.toolCount} tools` : ""),
    icon: getToolCategoryIcon(
      int.id,
      { size: 18, width: 18, height: 18, showBackground: false },
      int.iconUrl,
    ),
    keywords: `${int.category} ${int.status} ${int.description ?? ""}`,
    dot: DOT[int.status],
    primary: connectable ? connect : open,
    actions: connectable ? [open] : [disconnect],
  };
}

/** The whole catalog is surfaced — connected ones to manage, the rest to connect. */
export const buildIntegrationItems = (
  integrations: Integration[],
  ctx: BuildCtx,
  deps: IntegrationDeps,
): CommandItem[] =>
  [...integrations]
    .sort(byConnectionStateThenName)
    .slice(0, MAX_ITEMS)
    .map((int) => buildIntegrationItem(int, ctx, deps));
