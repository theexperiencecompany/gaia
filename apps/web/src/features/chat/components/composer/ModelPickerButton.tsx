import {
  Chip,
  Select,
  SelectItem,
  SelectSection,
  type SharedSelection,
} from "@heroui/react";
import Image from "next/image";
import type React from "react";
import { useMemo } from "react";

import { useUser, useUserActions } from "@/features/auth/hooks/useUser";

import {
  useCurrentUserModel,
  useModels,
  useSelectModel,
} from "../../hooks/useModels";

const ModelPickerButton: React.FC = () => {
  const { data: models, isLoading } = useModels();
  const selectModelMutation = useSelectModel();
  const currentModel = useCurrentUserModel();
  const user = useUser();
  const { setUser } = useUserActions();

  const handleSelectionChange = (keys: SharedSelection) => {
    const selectedKey = Array.from(keys)[0];
    if (selectedKey && typeof selectedKey === "string") {
      selectModelMutation.mutate(selectedKey);
      setUser({
        ...user,
        selected_model: selectedKey,
      });
    }
  };

  // Find the default model from the models list
  const defaultModel = useMemo(() => {
    return models?.find((model) => model.is_default);
  }, [models]);

  // Group models by provider and sort
  const groupedModels = useMemo(() => {
    if (!models) return {};

    const grouped = models.reduce(
      (acc, model) => {
        const provider = model.model_provider || "Unknown";
        if (!acc[provider]) {
          acc[provider] = [];
        }
        acc[provider].push(model);
        return acc;
      },
      {} as Record<string, typeof models>,
    );

    // Sort providers alphabetically and models within each provider
    const sortedGrouped: Record<string, typeof models> = {};
    Object.keys(grouped)
      .sort()
      .forEach((provider) => {
        sortedGrouped[provider] = grouped[provider].sort((a, b) => {
          // First, prioritize selected model
          if (currentModel?.model_id === a.model_id) return -1;
          if (currentModel?.model_id === b.model_id) return 1;

          // Then, prioritize default model
          if (a.is_default && !b.is_default) return -1;
          if (b.is_default && !a.is_default) return 1;

          // Finally, sort alphabetically by name
          return a.name.localeCompare(b.name);
        });
      });

    return sortedGrouped;
  }, [models, currentModel]);

  const headingClasses =
    "flex w-full sticky top-0 pt-4 z-20 py-2 px-2 bg-zinc-800  text-zinc-200 text-xs font-medium capitalize";

  // Don't render the button if models are still loading or not available
  if (isLoading || !models || models.length === 0) {
    return null;
  }

  const selectedModelId =
    currentModel?.model_id || defaultModel?.model_id || "";

  return (
    <Select
      placeholder="Model"
      selectedKeys={selectedModelId ? new Set([selectedModelId]) : new Set()}
      onSelectionChange={handleSelectionChange}
      isDisabled={selectModelMutation.isPending}
      size="sm"
      variant={"flat"}
      aria-label="Select AI Model"
      className="w-fit! max-w-none!"
      popoverProps={{
        classNames: {
          content: "min-w-[300px] max-w-none bg-zinc-800",
        },
      }}
      classNames={{
        trigger:
          "cursor-pointer bg-transparent transition hover:bg-zinc-800 !min-w-fit !w-auto !max-w-none whitespace-nowrap pl-3 pr-8",
        value: "text-zinc-400! text-xs font-medium whitespace-nowrap !w-auto ",
        base: "!max-w-none !w-auto",
        innerWrapper: "!w-auto !max-w-none",
        mainWrapper: "!w-auto !max-w-none",
      }}
      scrollShadowProps={{
        isEnabled: false,
      }}
      startContent={
        currentModel?.logo_url && (
          <Image
            src={currentModel.logo_url}
            alt={currentModel.name}
            height={40}
            width={40}
            className={`h-4 w-4 object-contain`}
          />
        )
      }
      renderValue={(items) => {
        if (!items.length) return "Model";
        const item = items[0];
        const model = models?.find((m) => m.model_id === item.key);
        return <span>{model?.name || "Model"}</span>;
      }}
    >
      {Object.entries(groupedModels).map(([provider, providerModels]) => (
        <SelectSection
          key={provider}
          classNames={{
            heading: headingClasses,
          }}
          title={provider}
        >
          {providerModels?.map((model) => {
            const isFree = model.lowest_tier.toLowerCase() === "free";

            return (
              <SelectItem
                key={model.model_id}
                textValue={`${model.name}${model.is_default ? " (Default)" : ""}`}
                classNames={{
                  title: "text-zinc-200",
                  description: "text-zinc-400 mt-1",
                }}
                startContent={
                  <div className="flex items-center gap-2">
                    {model.logo_url && (
                      <Image
                        src={model.logo_url}
                        alt={model.name}
                        height={40}
                        width={40}
                        className="h-4 w-4 object-contain"
                      />
                    )}
                  </div>
                }
              >
                <div className="flex items-center justify-between gap-2 w-full">
                  <span className="text-nowrap">{model.name}</span>
                  <div className="flex items-center gap-1">
                    {model.is_default && (
                      <Chip size="sm" color="success" variant="flat">
                        Default
                      </Chip>
                    )}
                    {isFree ? (
                      <Chip size="sm" color="default" variant="flat">
                        Free
                      </Chip>
                    ) : (
                      <Chip size="sm" color="warning" variant="flat">
                        Pro
                      </Chip>
                    )}
                  </div>
                </div>
              </SelectItem>
            );
          }) || []}
        </SelectSection>
      ))}
    </Select>
  );
};

export default ModelPickerButton;
