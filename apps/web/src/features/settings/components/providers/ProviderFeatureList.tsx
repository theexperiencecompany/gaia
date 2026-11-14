"use client";

import { Accordion } from "@heroui/react";
import type { ProviderFeature } from "@shared/api/generated";
import { accordionVariants } from "@/components/shared/accordionVariants";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { FeatureProviderPicker } from "./FeatureProviderPicker";
import { featureState } from "./featureState";
import { type FeatureGroup, featureAnchorId } from "./providerRows";
import { StatusBadge } from "./StatusBadge";

const accordionStyles = accordionVariants({ variant: "light" });

interface ProviderFeatureListProps {
  groups: FeatureGroup[];
  catalog: ProviderCatalog;
  status: SetupStatus | undefined;
  /** The feature to open on arrival, e.g. one a link pointed at. */
  openFeature?: ProviderFeature | null;
}

/** Each feature as one compact row with its status; a row expands to its provider picker. */
export function ProviderFeatureList({
  groups,
  catalog,
  status,
  openFeature = null,
}: ProviderFeatureListProps) {
  return (
    <Accordion
      allowsMultipleExpanded
      variant="default"
      defaultExpandedKeys={openFeature ? [openFeature] : []}
      className={accordionStyles.base({ className: "rounded-2xl bg-zinc-900" })}
    >
      {groups.map((group) => {
        const state = featureState(group, catalog);
        return (
          <Accordion.Item key={group.key} id={group.key}>
            <Accordion.Heading id={featureAnchorId(group.key)}>
              <Accordion.Trigger className="text-sm">
                <span className="flex flex-col items-start gap-0.5">
                  <span className="flex items-center gap-2">
                    <span className="font-medium text-zinc-100">
                      {group.spec.label}
                    </span>
                    <StatusBadge
                      label={state.badge}
                      active={state.tone === "working"}
                    />
                  </span>
                  <span className="line-clamp-1 text-xs text-zinc-500">
                    {state.summary}
                  </span>
                </span>
                <Accordion.Indicator />
              </Accordion.Trigger>
            </Accordion.Heading>
            <Accordion.Panel>
              <div className="pb-4">
                <FeatureProviderPicker
                  group={group}
                  catalog={catalog}
                  status={status}
                />
              </div>
            </Accordion.Panel>
          </Accordion.Item>
        );
      })}
    </Accordion>
  );
}
