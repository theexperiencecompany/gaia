import {
  ComboBox,
  EmptyState,
  Header,
  Label,
  ListBox,
  Skeleton,
} from "@heroui/react";
import type React from "react";
import { ComboBoxInput } from "@/components/shared/ComboBoxInput";
import { fieldVariants } from "@/components/shared/fieldVariants";
import { GaiaListBoxItem } from "@/components/shared/GaiaListBoxItem";
import { toneVariants } from "@/components/shared/tone";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useTriggerFilter } from "@/features/workflows/hooks/useTriggerFilter";
import type { TriggerSchema } from "@/features/workflows/triggers/types/base";

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

// HeroUI collections need Section/Item elements as direct children, so this is a render helper, not a component.
function renderTriggerSections(
  groupedTriggers: Record<string, TriggerSchema[]>,
  integrationStatusMap: Map<string, boolean>,
) {
  return Object.entries(groupedTriggers)
    .sort(([aId], [bId]) => {
      const aConnected = integrationStatusMap.get(aId) ?? false;
      const bConnected = integrationStatusMap.get(bId) ?? false;
      if (aConnected && !bConnected) return -1;
      if (!aConnected && bConnected) return 1;
      return 0;
    })
    .map(([integrationId, schemas]) => (
      <ListBox.Section key={integrationId} id={integrationId}>
        <Header className={toneVariants({ tone: "faint", className: "py-1" })}>
          {formatIntegrationName(integrationId)}
        </Header>
        {(schemas || []).map((schema) => (
          <GaiaListBoxItem
            key={schema.slug}
            id={schema.slug}
            textValue={schema.name}
            className="group"
          >
            {getToolCategoryIcon(schema.integration_id, {
              width: 20,
              height: 20,
              showBackground: false,
            })}
            <div className="flex flex-col">
              <span className="text-sm">{schema.name}</span>
              <span className="text-xs text-zinc-500 group-data-[hover=true]:text-zinc-300">
                {schema.description}
              </span>
            </div>
          </GaiaListBoxItem>
        ))}
      </ListBox.Section>
    ));
}

export function TriggerAutocomplete({
  selectedTrigger,
  onTriggerChange,
  triggerSchemas,
  isLoading,
  integrationStatusMap,
}: TriggerAutocompleteProps) {
  const { filterValue, setFilterValue, selectedSchema, groupedTriggers } =
    useTriggerFilter(selectedTrigger, triggerSchemas);
  const normalizedSelectedKey = selectedSchema?.slug ?? selectedTrigger;

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
      <ComboBox
        aria-label="Choose an event"
        className={fieldVariants({
          labelPlacement: "inside",
          className: "w-full",
        })}
        allowsEmptyCollection
        defaultFilter={() => true}
        inputValue={filterValue}
        onInputChange={handleInputChange}
        selectedKey={normalizedSelectedKey}
        onSelectionChange={handleSelectionChange}
      >
        <Label>Event</Label>
        <ComboBoxInput
          placeholder="Search apps and events..."
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
        />
        <ComboBox.Popover>
          <ListBox
            aria-label="Triggers"
            className={
              Object.keys(groupedTriggers).length > 2
                ? "min-h-[300px]"
                : "h-fit"
            }
            renderEmptyState={() => (
              <EmptyState>No matching triggers found.</EmptyState>
            )}
          >
            {renderTriggerSections(groupedTriggers, integrationStatusMap)}
          </ListBox>
        </ComboBox.Popover>
      </ComboBox>

      {selectedSchema && (
        <p className="px-1 text-xs text-zinc-500">
          {selectedSchema.description}
        </p>
      )}
    </div>
  );
}
