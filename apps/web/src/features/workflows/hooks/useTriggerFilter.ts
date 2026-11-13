import Fuse from "fuse.js";
import { useMemo, useState } from "react";
import type { TriggerSchema } from "@/features/workflows/triggers/types/base";
import { findTriggerSchema } from "@/features/workflows/triggers/utils";

function syncedFilterValue(
  selectedTrigger: string | null,
  selectedSchema: TriggerSchema | undefined,
  schemasLoaded: boolean,
  current: string,
): string {
  if (selectedSchema && selectedTrigger) return selectedSchema.name;
  // No selection, or schemas loaded without this slug: clear so it isn't a ghost selection.
  if (!selectedTrigger || schemasLoaded) return "";
  // Schemas still loading: keep whatever the user sees for now.
  return current;
}

function groupByIntegration(
  schemas: TriggerSchema[],
): Record<string, TriggerSchema[]> {
  return schemas.reduce(
    (acc, schema) => {
      const integrationId = schema.integration_id || "other";
      if (!acc[integrationId]) {
        acc[integrationId] = [];
      }
      acc[integrationId].push(schema);
      return acc;
    },
    {} as Record<string, TriggerSchema[]>,
  );
}

export function useTriggerFilter(
  selectedTrigger: string | null,
  triggerSchemas: TriggerSchema[] | undefined,
) {
  const [filterValue, setFilterValue] = useState("");
  const selectedSchema = findTriggerSchema(
    triggerSchemas,
    selectedTrigger ?? "",
  );

  // Render-time adjustment instead of an effect: the key snapshots every input
  // of the sync, so the text is correct on first paint and never stale.
  const displaySyncKey = `${selectedTrigger ?? ""}|${triggerSchemas !== undefined}|${selectedSchema?.name ?? ""}`;
  const [syncedDisplayKey, setSyncedDisplayKey] = useState(displaySyncKey);
  if (displaySyncKey !== syncedDisplayKey) {
    setSyncedDisplayKey(displaySyncKey);
    const next = syncedFilterValue(
      selectedTrigger,
      selectedSchema,
      triggerSchemas !== undefined,
      filterValue,
    );
    if (next !== filterValue) {
      setFilterValue(next);
    }
  }

  const fuse = useMemo(() => {
    if (!triggerSchemas) return null;
    return new Fuse(triggerSchemas, {
      keys: [
        "name",
        "description",
        "integration_id",
        { name: "slug", weight: 0.5 },
      ],
      threshold: 0.3,
      distance: 100,
    });
  }, [triggerSchemas]);

  const filteredSchemas = useMemo(() => {
    if (!triggerSchemas) return [];
    if (!filterValue) return triggerSchemas;
    if (selectedSchema && filterValue === selectedSchema.name) {
      return triggerSchemas;
    }
    if (fuse) {
      return fuse.search(filterValue).map((result) => result.item);
    }
    return triggerSchemas;
  }, [triggerSchemas, filterValue, fuse, selectedSchema]);

  const groupedTriggers = useMemo(
    () => groupByIntegration(filteredSchemas),
    [filteredSchemas],
  );

  return {
    filterValue,
    setFilterValue,
    selectedSchema,
    filteredSchemas,
    groupedTriggers,
  };
}
