/**
 * Wizard step 3 — optional. Two kinds of setup, told apart up front: your
 * apps (accounts you sign into, through the integrations feature's own
 * connect flow) and tool keys (keys behind GAIA's own tools, as the same
 * compact feature list Settings shows).
 */

"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { CircleArrowUpRight02Icon, ConnectIcon, KeyIcon } from "@icons";
import {
  CONNECT_ACTION_LABEL,
  integrationConnectionState,
} from "@shared/utils";
import * as m from "motion/react-m";
import Link from "next/link";
import { useMemo } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import { COMPOSIO_SETUP_PATH } from "@/features/settings/api/composioSetupApi";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { ProviderFeatureList } from "@/features/settings/components/providers/ProviderFeatureList";
import { resolveFeatureGroup } from "@/features/settings/components/providers/providerRows";
import { isProviderConfigured } from "@/features/settings/hooks/useSetupStatus";
import { WIZARD_TOOL_FEATURES } from "../../constants";
import { StepSectionHeader } from "./StepSectionHeader";

const MAX_SUGGESTED = 6;

interface IntegrationsStepProps {
  status: SetupStatus;
  catalog: ProviderCatalog;
  /** Fired after a tool-key save so the wizard refreshes setup status. */
  onSaved: () => void;
}

export function IntegrationsStep({
  status,
  catalog,
  onSaved,
}: IntegrationsStepProps) {
  const { integrations, isLoading, connectIntegration } = useIntegrations();
  const hasComposioKey = isProviderConfigured(status, "composio");

  const { suggested, connectedCount, needsSetupCount } = useMemo(() => {
    const connectable = integrations.filter((integration) => {
      const state = integrationConnectionState(integration.status);
      const isAvailable =
        integration.source === "custom" || integration.available;
      // Pending ("added, never authenticated") rows stay out of the wizard —
      // they resolve through the integrations page's deep-link handling.
      return (
        state !== "connected" &&
        state !== "pending" &&
        isAvailable &&
        !integration.instanceSetupRequired
      );
    });
    return {
      suggested: connectable.slice(0, MAX_SUGGESTED),
      connectedCount: integrations.filter(
        (i) => integrationConnectionState(i.status) === "connected",
      ).length,
      needsSetupCount: integrations.filter((i) => i.instanceSetupRequired)
        .length,
    };
  }, [integrations]);

  return (
    <m.div className="flex w-full flex-col gap-3" {...MOTION_FADE_UP}>
      <div className="w-full rounded-2xl bg-zinc-800 p-4">
        <StepSectionHeader
          icon={<ConnectIcon className="size-4" />}
          title="Your apps"
          description="Accounts you sign into, like Gmail or Calendar, so GAIA can work in them."
          accessory={
            connectedCount > 0 && (
              <Chip size="sm" variant="flat" color="success">
                {connectedCount} connected
              </Chip>
            )
          }
        />
        {needsSetupCount > 0 && (
          <div className="mb-3 flex items-center justify-between gap-3 rounded-2xl bg-zinc-900 p-3">
            <p className="text-xs text-zinc-400">
              {needsSetupCount} apps, like Gmail and GitHub,{" "}
              {hasComposioKey
                ? "need enabling on this instance first."
                : "need a Composio key first."}
            </p>
            <Button
              as={Link}
              href={COMPOSIO_SETUP_PATH}
              size="sm"
              variant="flat"
              color="primary"
              className="shrink-0"
            >
              {hasComposioKey ? "Set them up" : "Add Composio key"}
            </Button>
          </div>
        )}

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
        <StepSectionHeader
          icon={<KeyIcon className="size-4" />}
          title="Tool keys"
          description="Keys that power GAIA's own tools, like sending email or running code."
        />
        <ProviderFeatureList
          groups={WIZARD_TOOL_FEATURES.map((feature) =>
            resolveFeatureGroup(feature, catalog, status),
          )}
          catalog={catalog}
          status={status}
          onSaved={onSaved}
        />
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
