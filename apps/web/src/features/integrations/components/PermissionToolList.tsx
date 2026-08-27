"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Switch } from "@heroui/switch";
import { Search01Icon } from "@icons";
import {
  type IntegrationPermissions,
  useToolFilter,
} from "@/features/integrations/hooks/useIntegrationPermissions";
import type { IntegrationToolEntry } from "@/features/integrations/hooks/useIntegrationTools";
import {
  isModeInert,
  SEARCH_THRESHOLD,
  TOOL_SECTIONS,
} from "@/features/integrations/utils/permissionCopy";

import { PermissionCard } from "./PermissionCard";

interface PermissionToolListProps {
  tools: IntegrationToolEntry[];
  permissions: IntegrationPermissions;
}

/**
 * The modal's second decision: which of this integration's tools GAIA is
 * allowed to stop on. When the chosen mode is "Never" every switch here is
 * saved but ignored, so the list says so up front and offers the one press
 * that makes it mean something again.
 */
export const PermissionToolList = ({
  tools,
  permissions,
}: PermissionToolListProps) => {
  const { query, setQuery, visible } = useToolFilter(tools);
  const inert = isModeInert(permissions.mode);
  const grouped = visible.some(
    (tool) => tool.destructive !== visible[0]?.destructive,
  );

  return (
    <PermissionCard
      title="Actions GAIA asks about"
      description={`${permissions.askCount} of ${tools.length} turned on. Everything else runs without asking.`}
      action={
        permissions.deviations > 0 && (
          <Button
            size="sm"
            variant="light"
            className="-mr-1 h-7 shrink-0 px-2 text-xs text-zinc-400"
            isLoading={permissions.isSavingTools}
            onPress={permissions.resetToDefaults}
          >
            Reset to defaults
          </Button>
        )
      }
    >
      {inert && (
        <div className="mb-2 flex items-center gap-3 rounded-xl bg-amber-400/10 px-3 py-2">
          <p className="flex-1 text-xs leading-relaxed text-amber-400">
            Nothing here will stop GAIA until you change the setting above.
          </p>
          <Button
            size="sm"
            variant="flat"
            className="h-7 shrink-0"
            isLoading={permissions.isSavingMode}
            onPress={() => permissions.changeMode("auto")}
          >
            Turn on
          </Button>
        </div>
      )}

      {tools.length > SEARCH_THRESHOLD && (
        <Input
          size="sm"
          variant="flat"
          className="mb-2"
          placeholder="Search tools"
          value={query}
          onValueChange={setQuery}
          startContent={<Search01Icon className="size-4 text-zinc-500" />}
        />
      )}

      {TOOL_SECTIONS.map(({ key, title, destructive }) => {
        const items = visible.filter(
          (tool) => tool.destructive === destructive,
        );
        if (items.length === 0) return null;
        return (
          <div key={key} className="mb-3 last:mb-0">
            {/* A heading only earns its place when there is a second group to
                tell this one apart from. */}
            {grouped && (
              <h4 className="px-2 pb-1 text-xs font-medium text-zinc-500">
                {title}
              </h4>
            )}
            {items.map((tool) => (
              <div
                key={tool.name}
                className="flex items-center justify-between gap-3 rounded-xl px-2 py-1.5 hover:bg-zinc-800/60"
              >
                <span className="min-w-0 truncate text-sm text-zinc-300">
                  {tool.label}
                </span>
                <Switch
                  size="sm"
                  isSelected={permissions.asks(tool)}
                  onValueChange={(next) => permissions.toggle(tool, next)}
                  aria-label={`Ask before running ${tool.label}`}
                />
              </div>
            ))}
          </div>
        );
      })}

      {visible.length === 0 && (
        <p className="py-8 text-center text-xs text-zinc-500">
          No tools match.
        </p>
      )}
    </PermissionCard>
  );
};
