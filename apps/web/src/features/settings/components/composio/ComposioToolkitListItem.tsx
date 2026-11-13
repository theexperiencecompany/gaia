"use client";

import { Chip } from "@heroui/react";
import { GaiaButton } from "@/components/shared/GaiaButton";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import type { ComposioCatalogEntry } from "@/features/settings/api/composioSetupApi";

const STATUS_CHIP: Record<
  ComposioCatalogEntry["status"],
  { label: string; color: "success" | "accent" | "default" }
> = {
  built_in: { label: "Built in", color: "accent" },
  enabled: { label: "Enabled", color: "success" },
  available: { label: "Available", color: "default" },
  unsupported: { label: "No sign-in", color: "default" },
};

interface ComposioToolkitListItemProps {
  toolkit: ComposioCatalogEntry;
  isSelected: boolean;
  onSelect: (slug: string) => void;
}

/** One catalog row: logo, name, category and what it is on this instance. */
export function ComposioToolkitListItem({
  toolkit,
  isSelected,
  onSelect,
}: ComposioToolkitListItemProps) {
  const chip =
    toolkit.status === "built_in" && !toolkit.set_up
      ? { label: "Built in, not set up", color: "default" as const }
      : STATUS_CHIP[toolkit.status];

  return (
    <GaiaButton
      variant={isSelected ? "secondary" : "ghost"}
      size="sm"
      className="h-auto w-full shrink-0 justify-start gap-3 text-left"
      onPress={() => onSelect(toolkit.slug)}
    >
      <IntegrationIcon
        integrationId={toolkit.slug}
        iconUrl={toolkit.logo}
        size={28}
      />
      <span className="flex min-w-0 flex-1 flex-col py-2">
        <span className="truncate text-sm text-zinc-100">{toolkit.name}</span>
        <span className="truncate text-xs text-zinc-500">
          {toolkit.categories[0] ?? "other"}
        </span>
      </span>
      <Chip size="sm" variant="soft" color={chip.color}>
        {chip.label}
      </Chip>
    </GaiaButton>
  );
}
