"use client";

import { Accordion, AccordionItem } from "@heroui/accordion";
import type { ProviderFeature } from "@shared/api/generated";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { FeatureProviderPicker } from "./FeatureProviderPicker";
import { featureState } from "./featureState";
import { type FeatureGroup, featureAnchorId } from "./providerRows";
import { StatusBadge } from "./StatusBadge";

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
      selectionMode="multiple"
      variant="light"
      defaultExpandedKeys={openFeature ? [openFeature] : []}
      className="rounded-2xl bg-zinc-900 px-2"
      itemClasses={{ title: "text-sm", content: "pb-4" }}
    >
      {groups.map((group) => {
        const state = featureState(group, catalog);
        return (
          <AccordionItem
            key={group.key}
            id={featureAnchorId(group.key)}
            aria-label={group.spec.label}
            title={
              <span className="flex items-center gap-2">
                <span className="font-medium text-zinc-100">
                  {group.spec.label}
                </span>
                <StatusBadge
                  label={state.badge}
                  active={state.tone === "working"}
                />
              </span>
            }
            subtitle={
              <span className="line-clamp-1 text-xs text-zinc-500">
                {state.summary}
              </span>
            }
          >
            <FeatureProviderPicker
              group={group}
              catalog={catalog}
              status={status}
            />
          </AccordionItem>
        );
      })}
    </Accordion>
  );
}
