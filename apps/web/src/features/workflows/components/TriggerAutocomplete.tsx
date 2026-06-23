import {
  Autocomplete,
  AutocompleteItem,
  AutocompleteSection,
} from "@heroui/autocomplete";
import { Skeleton } from "@heroui/skeleton";
import Fuse from "fuse.js";
import type React from "react";
import { useEffect, useMemo, useState } from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { TriggerSchema } from "@/features/workflows/triggers/types/base";
import { findTriggerSchema } from "@/features/workflows/triggers/utils";

interface TriggerAutocompleteProps {
  selectedTrigger: string | null;
  onTriggerChange: (trigger: string | null) => void;
  triggerSchemas: TriggerSchema[] | undefined;
  isLoading?: boolean;
  integrationStatusMap: Map<string, boolean>;
}

function formatIntegrationName(integrationId: string): string {
  return integrationId
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function TriggerAutocomplete({
  selectedTrigger,
  onTriggerChange,
  triggerSchemas,
  isLoading,
  integrationStatusMap,
}: TriggerAutocompleteProps) {
  const [filterValue, setFilterValue] = useState("");

  const selectedSchema = findTriggerSchema(
    triggerSchemas,
    selectedTrigger ?? "",
  );
  const normalizedSelectedKey = selectedSchema?.slug ?? selectedTrigger;

  useEffect(() => {
    if (selectedSchema && selectedTrigger) {
      setFilterValue(selectedSchema.name);
    } else if (!selectedTrigger) {
      setFilterValue("");
    } else if (selectedTrigger && triggerSchemas !== undefined) {
      // Schemas loaded but this trigger slug wasn't found — clear the display
      // so it doesn't appear as a ghost selection
      setFilterValue("");
    }
  }, [selectedTrigger, selectedSchema?.slug, triggerSchemas]);

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

  const groupedTriggers = useMemo(() => {
    return filteredSchemas.reduce(
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
  }, [filteredSchemas]);

  const handleSelectionChange = (key: React.Key | null) => {
    if (!key) {
      onTriggerChange(null);
      setFilterValue("");
      return;
    }

    const trigger = String(key);

    // Any trigger can be selected; if its integration isn't connected, the
    // settings panel shows the inline connection prompt for it.
    const schema = triggerSchemas?.find((s) => s.slug === trigger);

    onTriggerChange(trigger);
    if (schema) {
      setFilterValue(schema.name);
    }
  };

  const handleInputChange = (value: string) => {
    setFilterValue(value);
    if (value === "") {
      onTriggerChange(null);
    }
  };

  if (isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-10 w-full rounded-xl" />
      </div>
    );
  }

  return (
    <div className="w-full space-y-2">
      <Autocomplete
        aria-label="Choose an event"
        label="Event"
        placeholder="Search apps and events..."
        className="w-full"
        selectedKey={normalizedSelectedKey}
        onSelectionChange={handleSelectionChange}
        onInputChange={handleInputChange}
        inputValue={filterValue}
        items={filteredSchemas}
        defaultFilter={() => true}
        classNames={{
          listboxWrapper: `${Object.keys(groupedTriggers).length > 2 ? "min-h-[300px]" : "h-fit"} p-1`,
        }}
        startContent={
          selectedSchema &&
          getToolCategoryIcon(selectedSchema.integration_id, {
            width: 20,
            height: 20,
            showBackground: false,
          })
        }
        isClearable
        onClear={() => {
          setFilterValue("");
          onTriggerChange(null);
        }}
        listboxProps={{
          emptyContent: "No matching triggers found.",
        }}
      >
        {Object.entries(groupedTriggers)
          .sort(([aId], [bId]) => {
            const aConnected = integrationStatusMap.get(aId) ?? false;
            const bConnected = integrationStatusMap.get(bId) ?? false;
            if (aConnected && !bConnected) return -1;
            if (!aConnected && bConnected) return 1;
            return 0;
          })
          .map(([integrationId, schemas]) => {
            const schemaList = schemas || [];

            const triggerItems = schemaList.map((schema) => (
              <AutocompleteItem
                key={schema.slug}
                textValue={schema.name}
                startContent={getToolCategoryIcon(schema.integration_id, {
                  width: 20,
                  height: 20,
                  showBackground: false,
                })}
                className="group"
              >
                <div className="flex flex-col">
                  <span className="text-small">{schema.name}</span>
                  <span className="text-tiny text-zinc-500 group-data-[hover=true]:text-zinc-300">
                    {schema.description}
                  </span>
                </div>
              </AutocompleteItem>
            ));

            return (
              <AutocompleteSection
                key={integrationId}
                classNames={{
                  base: "mb-1",
                  heading: "px-2 py-1 text-tiny font-medium text-zinc-500",
                }}
                title={formatIntegrationName(integrationId)}
              >
                {triggerItems}
              </AutocompleteSection>
            );
          })}
      </Autocomplete>

      {selectedSchema && (
        <p className="px-1 text-xs text-zinc-500">
          {selectedSchema.description}
        </p>
      )}
    </div>
  );
}
