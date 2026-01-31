import {
  Autocomplete,
  AutocompleteItem,
  AutocompleteSection,
} from "@heroui/autocomplete";
import Fuse from "fuse.js";
import type React from "react";
import { useEffect, useMemo, useState } from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import type { TriggerSchema } from "@/features/workflows/triggers";

interface TriggerAutocompleteProps {
  selectedTrigger: string | null;
  onTriggerChange: (trigger: string | null) => void;
  triggerSchemas: TriggerSchema[] | undefined;
  isLoading?: boolean;
  integrationStatusMap: Map<string, boolean>;
  onConnectIntegration: (integrationId: string) => void;
}

// Format integration ID to display name
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
  onConnectIntegration,
}: TriggerAutocompleteProps) {
  const [filterValue, setFilterValue] = useState("");

  const selectedSchema = triggerSchemas?.find(
    (s) => s.slug === selectedTrigger,
  );

  // Sync filterValue with selected trigger name when editing
  useEffect(() => {
    if (selectedSchema && !filterValue) {
      setFilterValue(selectedSchema.name);
    }
  }, [selectedSchema, filterValue]);

  // Create Fuse instance for fuzzy search
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

  // Filter triggers based on search input
  const filteredSchemas = useMemo(() => {
    if (!triggerSchemas) return [];
    if (!filterValue) return triggerSchemas;

    if (fuse) {
      return fuse.search(filterValue).map((result) => result.item);
    }
    return triggerSchemas;
  }, [triggerSchemas, filterValue, fuse]);

  // Group filtered triggers by integration
  const groupedTriggers = useMemo(() => {
    const schemasToGroup = filteredSchemas;

    return schemasToGroup.reduce(
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

    // Handle connection items
    if (trigger.startsWith("connect-")) {
      const integrationId = trigger.replace("connect-", "");
      onConnectIntegration(integrationId);
      // Reset filter/selection logic if needed, but since we're opening a popup/redirect,
      // creating a seamless flow is better. We just don't select it as a trigger.
      return;
    }

    const schema = triggerSchemas?.find((s) => s.slug === trigger);

    // Check if integration is connected
    if (schema?.integration_id) {
      const isConnected = integrationStatusMap.get(schema.integration_id);
      if (!isConnected) {
        // Don't allow selection of disconnected integrations
        return;
      }
    }

    onTriggerChange(trigger);
    if (schema) {
      setFilterValue(schema.name);
    }
  };

  const handleInputChange = (value: string) => {
    setFilterValue(value);
    // If user clears input completely, clear the selection too
    if (value === "") {
      onTriggerChange(null);
    }
  };

  if (isLoading) {
    return <div className="animate-pulse h-12 bg-zinc-800 rounded-lg" />;
  }

  return (
    <div className="w-full space-y-2">
      <Autocomplete
        aria-label="Choose a trigger"
        label="Trigger"
        placeholder="Search or select a trigger..."
        className="w-full max-w-sm"
        selectedKey={selectedTrigger}
        onSelectionChange={handleSelectionChange}
        onInputChange={handleInputChange}
        inputValue={filterValue}
        items={filteredSchemas}
        defaultFilter={() => true}
        classNames={{
          listboxWrapper: `${
            Object.keys(groupedTriggers).length > 2 ? "min-h-[300px]" : "h-fit"
          } p-1`,
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
            // Connected integrations first
            if (aConnected && !bConnected) return -1;
            if (!aConnected && bConnected) return 1;
            return 0;
          })
          .map(([integrationId, schemas]) => {
            const isConnected =
              integrationStatusMap.get(integrationId) ?? false;
            // Ensure schemas exists before mapping
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

            const connectionItem = !isConnected ? (
              <AutocompleteItem
                key={`connect-${integrationId}`}
                textValue={`Connect ${formatIntegrationName(integrationId)}`}
                className="my-2 bg-primary text-primary-foreground font-medium data-[hover=true]:bg-primary/90 data-[hover=true]:text-primary-foreground/90 text-center"
              >
                <div className="text-center">
                  Connect {formatIntegrationName(integrationId)}
                </div>
              </AutocompleteItem>
            ) : null;

            if (connectionItem) {
              triggerItems.unshift(connectionItem);
            }

            return (
              <AutocompleteSection
                key={integrationId}
                className="border-b-1 pb-4 mb-4 border-zinc-800"
                title={formatIntegrationName(integrationId)}
              >
                {triggerItems}
              </AutocompleteSection>
            );
          })}
      </Autocomplete>

      {/* Trigger description helper text */}
      {selectedSchema && (
        <p className="px-1 text-xs text-zinc-500">
          {selectedSchema.description}
        </p>
      )}
    </div>
  );
}
