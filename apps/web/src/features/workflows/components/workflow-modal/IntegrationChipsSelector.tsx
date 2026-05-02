"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { Spinner } from "@heroui/spinner";
import { Add01Icon, Cancel01Icon, Tick02Icon } from "@icons";
import { useState } from "react";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import type { Integration } from "@/features/integrations/types";
import { cn } from "@/lib/utils";

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
            <Button
              isIconOnly
              size="sm"
              variant="light"
              onPress={() => removeIntegration(integration.slug)}
              className="ml-0.5 h-5 min-w-5 rounded-full p-0 hover:bg-primary/20"
              aria-label={`Remove ${integration.name}`}
            >
              <Cancel01Icon className="h-3 w-3" />
            </Button>
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
            aria-label="Select integrations for this workflow"
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
              <div className="max-h-52 space-y-0.5 overflow-y-auto">
                {connectedIntegrations.map((integration) => {
                  const isSelected = selectedSlugs.includes(integration.slug);
                  return (
                    <Button
                      key={integration.slug}
                      variant="light"
                      onPress={() => toggleIntegration(integration.slug)}
                      aria-pressed={isSelected}
                      aria-label={`${isSelected ? "Remove" : "Add"} ${integration.name}`}
                      className={cn(
                        "flex w-full justify-start gap-2 rounded-xl px-2 py-1.5 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                        isSelected
                          ? "bg-primary/15 text-primary"
                          : "text-foreground/70",
                      )}
                    >
                      <IntegrationIcon integration={integration} />
                      <span className="flex-1 truncate">
                        {integration.name}
                      </span>
                      {isSelected && (
                        <Tick02Icon className="h-3.5 w-3.5 shrink-0" />
                      )}
                    </Button>
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
