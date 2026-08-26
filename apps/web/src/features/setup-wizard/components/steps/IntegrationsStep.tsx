/**
 * Wizard step 3 — optional account connections. Reuses the integrations
 * feature's own `useIntegrations` hook for data and the connect flow
 * (OAuth redirects away and resumes after the callback), plus the shared
 * connection-state helpers that render Connect/Reconnect labels elsewhere.
 * If the catalog can't load, falls back to a static link to /integrations.
 * Below the app catalog sit the tool/integration provider keys (composio,
 * e2b, …) on the same ProviderSetupCard pattern as the search step.
 */

"use client";

import { Button } from "@heroui/button";
import { Skeleton } from "@heroui/skeleton";
import { CircleArrowUpRight02Icon } from "@icons";
import {
  CONNECT_ACTION_LABEL,
  integrationConnectionState,
} from "@shared/utils";
import * as m from "motion/react-m";
import Link from "next/link";
import { useMemo } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { SetupStatus } from "@/features/settings/api/providersApi";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import { MOTION_FADE_UP, TOOL_PROVIDER_CARDS } from "../../constants";
import { ProviderSetupCard } from "../ProviderSetupCard";

const MAX_SUGGESTED = 6;

interface IntegrationsStepProps {
  status: SetupStatus;
  /** Fired after a tool-key save so the wizard refreshes setup status. */
  onSaved: () => void;
}

export function IntegrationsStep({ status, onSaved }: IntegrationsStepProps) {
  const { integrations, isLoading, connectIntegration } = useIntegrations();

  const { suggested, connectedCount } = useMemo(() => {
    const connectable = integrations.filter((integration) => {
      const state = integrationConnectionState(integration.status);
      const isAvailable =
        integration.source === "custom" || integration.available;
      // Pending ("added, never authenticated") rows stay out of the wizard —
      // they resolve through the integrations page's deep-link handling.
      return state !== "connected" && state !== "pending" && isAvailable;
    });
    return {
      suggested: connectable.slice(0, MAX_SUGGESTED),
      connectedCount: integrations.filter(
        (i) => integrationConnectionState(i.status) === "connected",
      ).length,
    };
  }, [integrations]);

  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      <div className="w-full rounded-2xl bg-zinc-800 p-4">
        <div className="mb-1 flex items-center justify-between gap-2">
          <p className="text-sm font-medium text-zinc-100">Your apps</p>
          {connectedCount > 0 && (
            <span className="rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs text-emerald-400">
              {connectedCount} connected
            </span>
          )}
        </div>
        <p className="mb-3 text-xs text-zinc-500">
          Pick a few now, or browse the full catalog later — connections live in
          Settings either way.
        </p>

        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton
                key={`integration-skeleton-${String(i)}`}
                className="h-12 w-full rounded-2xl bg-zinc-900"
              />
            ))}
          </div>
        ) : suggested.length === 0 ? (
          <p className="text-xs text-zinc-500">
            No integrations available right now — you can add them anytime from
            Settings.
          </p>
        ) : (
          <div className="space-y-2">
            {suggested.map((integration) => {
              const state = integrationConnectionState(integration.status);
              return (
                <div
                  key={integration.id}
                  className="flex min-h-12 items-center gap-3 rounded-2xl bg-zinc-900 p-3"
                >
                  <span className="shrink-0">
                    {getToolCategoryIcon(
                      integration.id,
                      {
                        size: 22,
                        width: 22,
                        height: 22,
                        showBackground: false,
                      },
                      integration.iconUrl,
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-zinc-200">
                      {integration.name}
                    </p>
                    <p className="truncate text-xs text-zinc-500">
                      {integration.description}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="flat"
                    color={state === "expired" ? "warning" : "primary"}
                    onPress={() => {
                      void connectIntegration(integration.id);
                    }}
                  >
                    {CONNECT_ACTION_LABEL[state]}
                  </Button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="w-full rounded-2xl bg-zinc-800 p-4">
        <p className="mb-1 text-sm font-medium text-zinc-100">Tool keys</p>
        <p className="mb-3 text-xs text-zinc-500">
          Optional. Add keys for the tools GAIA can use — every one can also be
          configured later in Settings.
        </p>
        <div className="space-y-2">
          {TOOL_PROVIDER_CARDS.map((config) => (
            <ProviderSetupCard
              key={config.key}
              config={config}
              isConfigured={isProviderConfigured(status, config.key)}
              onSaved={onSaved}
            />
          ))}
        </div>
      </div>

      <Button
        as={Link}
        href="/integrations"
        variant="light"
        size="sm"
        radius="full"
        endContent={<CircleArrowUpRight02Icon className="size-4" />}
        className="self-start text-zinc-400"
      >
        Browse all integrations
      </Button>
    </m.div>
  );
}
