"use client";

import { Autocomplete, AutocompleteItem } from "@heroui/autocomplete";
import { Chip } from "@heroui/chip";
import { memo, useCallback, useMemo, useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";

interface IntegrationChipsSelectorProps {
  readonly selectedSlugs: string[];
  readonly onChange: (slugs: string[]) => void;
}

function IntegrationIcon({ integration }: { integration: Integration }) {
  return getToolCategoryIcon(
    integration.id,
    { size: 14, width: 14, height: 14, showBackground: false },
    integration.iconUrl,
  );
}

function IntegrationChipsSelector({
  selectedSlugs,
  onChange,
}: IntegrationChipsSelectorProps) {
  const { integrations, isLoading } = useIntegrations();
  const [inputValue, setInputValue] = useState("");

  const connectedIntegrations = useMemo(
    () =>
      integrations.filter(
        (i) => i.status === "connected" || i.status === "created",
      ),
    [integrations],
  );

  const selectedSlugSet = useMemo(
    () => new Set(selectedSlugs),
    [selectedSlugs],
  );

  const selectedIntegrations = useMemo(
    () => connectedIntegrations.filter((i) => selectedSlugSet.has(i.slug)),
    [connectedIntegrations, selectedSlugSet],
  );

  const availableIntegrations = useMemo(() => {
    const query = inputValue.trim().toLowerCase();
    return connectedIntegrations.filter(
      (i) =>
        !selectedSlugSet.has(i.slug) &&
        (query === "" || i.name.toLowerCase().includes(query)),
    );
  }, [connectedIntegrations, selectedSlugSet, inputValue]);

  const handleSelectionChange = useCallback(
    (key: React.Key | null) => {
      if (key == null) return;
      const slug = String(key);
      if (!selectedSlugSet.has(slug)) {
        onChange([...selectedSlugs, slug]);
      }
      setInputValue("");
    },
    [onChange, selectedSlugs, selectedSlugSet],
  );

  const removeIntegration = useCallback(
    (slug: string) => {
      onChange(selectedSlugs.filter((s) => s !== slug));
    },
    [onChange, selectedSlugs],
  );

  if (!isLoading && connectedIntegrations.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      <Autocomplete
        aria-label="Add integration to this workflow"
        placeholder={
          selectedIntegrations.length === 0
            ? "Select integrations"
            : "Add integration"
        }
        description="Suggest Apps GAIA should use in this workflow"
        size="sm"
        variant="flat"
        isLoading={isLoading}
        items={availableIntegrations}
        selectedKey={null}
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSelectionChange={handleSelectionChange}
        menuTrigger="focus"
        className="max-w-sm"
      >
        {(integration) => (
          <AutocompleteItem
            key={integration.slug}
            textValue={integration.name}
            startContent={<IntegrationIcon integration={integration} />}
          >
            {integration.name}
          </AutocompleteItem>
        )}
      </Autocomplete>

      {selectedIntegrations.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {selectedIntegrations.map((integration) => (
            <Chip
              key={integration.slug}
              size="sm"
              variant="flat"
              color="primary"
              as="button"
              type="button"
              onClick={() => removeIntegration(integration.slug)}
              onClose={() => removeIntegration(integration.slug)}
              aria-label={`Remove ${integration.name}`}
              startContent={
                <span className="ml-1 flex items-center">
                  <IntegrationIcon integration={integration} />
                </span>
              }
              className="cursor-pointer transition-colors hover:bg-primary/30"
            >
              {integration.name}
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

export default memo(IntegrationChipsSelector);
