import {
  Chip,
  Select,
  SelectItem,
  SelectSection,
  SharedSelection,
} from "@heroui/react";
import Image from "next/image";
import React, { useMemo } from "react";

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

  const getTierDisplayName = (tier: string) => {
    return tier.charAt(0).toUpperCase() + tier.slice(1);
  };

  const getTierColor = (tier: string) => {
    switch (tier.toLowerCase()) {
      case "pro":
        return "text-amber-400";
      default:
        return "text-zinc-400";
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
    "flex w-full sticky top-0 z-20 py-2 px-2 bg-zinc-800  text-zinc-200 text-xs font-medium capitalize";

  // Don't render the button if models are still loading or not available
  if (isLoading || !models || models.length === 0) {
    return null;
  }

  return (
    <Select
      placeholder="Model"
      selectedKeys={
        currentModel?.model_id
          ? new Set([currentModel.model_id])
          : defaultModel?.model_id
            ? new Set([defaultModel.model_id])
            : new Set()
      }
      onSelectionChange={handleSelectionChange}
      isDisabled={selectModelMutation.isPending}
      size="sm"
      variant={"flat"}
      aria-label="Select AI Model"
      className="!w-fit !max-w-none"
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
        // Remove text-nowrap to prevent truncation
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
          {providerModels?.map((model) => (
            <SelectItem
              key={model.model_id}
              textValue={`${model.name}${model.is_default ? " (Default)" : ""}`}
              classNames={{
                title: "text-zinc-200",
                description: "text-zinc-400 mt-1",
              }}
              startContent={
                model.logo_url && (
                  <Image
                    src={model.logo_url}
                    alt={model.name}
                    height={40}
                    width={40}
                    className={`h-4 w-4 object-contain`}
                  />
                )
              }
              description={
                <div className="flex items-center justify-between text-xs">
                  <div className="flex items-center gap-2">
                    {model.lowest_tier.toLowerCase() !== "free" && (
                      <span className={getTierColor(model.lowest_tier)}>
                        {getTierDisplayName(model.lowest_tier)}+ Plan
                      </span>
                    )}
                  </div>
                </div>
              }
            >
              <div className="flex items-center justify-between gap-2">
                <span>{model.name}</span>
                {model.is_default && (
                  <Chip size="sm" color="success" variant="flat">
                    Default
                  </Chip>
                )}
              </div>
            </SelectItem>
          )) || []}
        </SelectSection>
      ))}
    </Select>
  );
};

export default ModelPickerButton;
