"use client";

import { Button, Chip } from "@heroui/react";
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
    <Button
      variant={isSelected ? "secondary" : "ghost"}
      className="h-auto w-full shrink-0 justify-start gap-3 rounded-lg px-3 py-2 text-left"
      onPress={() => onSelect(toolkit.slug)}
    >
      <IntegrationIcon
        integrationId={toolkit.slug}
        iconUrl={toolkit.logo}
        size={28}
      />
      <span className="flex min-w-0 flex-1 flex-col">
        <span className="truncate text-sm text-zinc-100">{toolkit.name}</span>
        <span className="truncate text-xs text-zinc-500">
          {toolkit.categories[0] ?? "other"}
        </span>
      </span>
      <Chip size="sm" variant="soft" color={chip.color}>
        {chip.label}
      </Chip>
    </Button>
  );
}
