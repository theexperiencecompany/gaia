"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Spinner } from "@heroui/spinner";
import { Add01Icon, Cancel01Icon } from "@icons";
import { useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";

interface IntegrationChipsSelectorProps {
  selectedSlugs: string[];
  onChange: (slugs: string[]) => void;
}

function IntegrationIcon({ integration }: { integration: Integration }) {
  return getToolCategoryIcon(
    integration.id,
    { size: 14, width: 14, height: 14, showBackground: false },
    integration.iconUrl,
  );
}

export default function IntegrationChipsSelector({
  selectedSlugs,
  onChange,
}: IntegrationChipsSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const { integrations, isLoading } = useIntegrations();

  const connectedIntegrations = integrations.filter(
    (i) => i.status === "connected" || i.status === "created",
  );

  const selectedIntegrations = connectedIntegrations.filter((i) =>
    selectedSlugs.includes(i.slug),
  );

  const toggleIntegration = (slug: string) => {
    if (selectedSlugs.includes(slug)) {
      onChange(selectedSlugs.filter((s) => s !== slug));
    } else {
      onChange([...selectedSlugs, slug]);
    }
  };

  const removeIntegration = (slug: string) => {
    onChange(selectedSlugs.filter((s) => s !== slug));
  };

  if (connectedIntegrations.length === 0 && !isLoading) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {selectedIntegrations.map((integration) => (
        <Chip
          key={integration.slug}
          size="sm"
          variant="flat"
          color="primary"
          startContent={
            <span className="ml-1">
              <IntegrationIcon integration={integration} />
            </span>
          }
          endContent={
            <button
              type="button"
              onClick={() => removeIntegration(integration.slug)}
              className="ml-0.5 flex items-center rounded-full p-0.5 hover:bg-primary/20"
              aria-label={`Remove ${integration.name}`}
            >
              <Cancel01Icon className="h-2.5 w-2.5" />
            </button>
          }
          className="pl-1 pr-1"
        >
          {integration.name}
        </Chip>
      ))}

      <Popover
        isOpen={isOpen}
        onOpenChange={setIsOpen}
        placement="bottom-start"
        offset={6}
      >
        <PopoverTrigger>
          <Button
            size="sm"
            variant="flat"
            isIconOnly
            startContent={<Add01Icon className="h-3 w-3" />}
            aria-label="Add integration hint"
            className="h-6 min-w-6 rounded-full text-zinc-400 hover:text-primary"
          />
        </PopoverTrigger>
        <PopoverContent className="w-64 p-2">
          <div className="w-full">
            <p className="mb-2 px-1 text-xs font-medium text-zinc-400">
              Hint step generation with your integrations
            </p>
            {isLoading ? (
              <div className="flex justify-center py-4">
                <Spinner size="sm" />
              </div>
            ) : (
              <div className="max-h-52 overflow-y-auto space-y-0.5">
                {connectedIntegrations.map((integration) => {
                  const isSelected = selectedSlugs.includes(integration.slug);
                  return (
                    <button
                      key={integration.slug}
                      type="button"
                      onClick={() => toggleIntegration(integration.slug)}
                      className={`flex w-full items-center gap-2 rounded-xl px-2 py-1.5 text-left text-sm transition-colors ${
                        isSelected
                          ? "bg-primary/15 text-primary"
                          : "hover:bg-zinc-800 text-zinc-300"
                      }`}
                    >
                      <IntegrationIcon integration={integration} />
                      <span className="flex-1 truncate">{integration.name}</span>
                      {isSelected && (
                        <span className="h-1.5 w-1.5 rounded-full bg-primary" />
                      )}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </PopoverContent>
      </Popover>
    </div>
  );
}
